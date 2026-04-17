import asyncio
import json
import logging
import platform
import random
import shutil
import time
from pathlib import Path

log = logging.getLogger("audiotool")

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from audio import get_backend
from config import config
from transcript import (
    assign_speaker_numbers,
    build_transcript_json,
    build_turns_json,
    parse_transcript,
    unique_speakers,
)
from tts import assign_voices, get_tts_provider

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")

app = FastAPI()
backend = get_backend()

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".mp4", ".flac", ".m4a"}


def _samples_dir() -> Path:
    return Path(config["samples_dir"])


class AppState:
    def __init__(self):
        self.loopback_running = False
        self.loopback_mode = "virtual-sink"
        self.loopback_process = None
        self.playback_process = None  # PlaybackHandle | None
        self.current_file = None
        self.volume = config["default_volume"]
        self.playback_duration = 0.0
        self.playback_started_at = 0.0
        self.playback_speed = 1.0
        self.playback_position = 0.0
        self.current_filepath = None
        self.sse_clients: list[asyncio.Queue] = []

    def to_dict(self):
        return {
            "loopback_running": self.loopback_running,
            "loopback_mode": self.loopback_mode,
            "current_file": self.current_file,
            "volume": self.volume,
            "playback_duration": self.playback_duration,
            "playback_started_at": self.playback_started_at,
            "playback_speed": self.playback_speed,
            "playback_position": self.playback_position,
        }


state = AppState()


class ConversationState:
    def __init__(self):
        self.running = False
        self.script = None
        self.turns = []
        self.current_turn = -1
        self.gap_min = config["conversation_gap_min"]
        self.gap_max = config["conversation_gap_max"]
        self.loopback1_process = None
        self.loopback2_process = None
        self.playback_process = None  # PlaybackHandle | None
        self.playback_duration = 0.0
        self.playback_started_at = 0.0
        self._task = None
        self.loopbacks_ready = False

    def to_dict(self):
        return {
            "conversation_running": self.running,
            "conversation_script": self.script,
            "conversation_turns": self.turns,
            "conversation_current_turn": self.current_turn,
            "conversation_gap_min": self.gap_min,
            "conversation_gap_max": self.gap_max,
            "conversation_playback_duration": self.playback_duration,
            "conversation_playback_started_at": self.playback_started_at,
            "conversation_loopbacks_ready": self.loopbacks_ready,
        }


conv_state = ConversationState()


class GenerationState:
    def __init__(self):
        self.active = False
        self.step = None  # "claude" | "tts" | None
        self.tts_total = 0
        self.tts_completed = 0
        self.error = None
        self.conversation_name = None
        self._task = None

    def to_dict(self):
        return {
            "gen_active": self.active,
            "gen_step": self.step,
            "gen_tts_total": self.tts_total,
            "gen_tts_completed": self.tts_completed,
            "gen_error": self.error,
            "gen_conversation_name": self.conversation_name,
        }


gen_state = GenerationState()


def _full_state_dict():
    d = state.to_dict()
    d.update(conv_state.to_dict())
    d.update(gen_state.to_dict())
    return d


async def broadcast_state():
    data = json.dumps(_full_state_dict())
    for queue in list(state.sse_clients):
        await queue.put(data)


@app.get("/")
async def index():
    html = (Path(__file__).parent / "static" / "index.html").read_text()
    return HTMLResponse(html)


@app.get("/api/files")
async def list_files():
    samples = _samples_dir()
    if not samples.is_dir():
        return {"files": []}
    files = sorted(
        f.name for f in samples.iterdir()
        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
    )
    return {"files": files}


@app.get("/api/sinks")
async def list_sinks():
    sinks = await backend.list_sinks()
    return {"sinks": sinks}


@app.get("/api/status")
async def status_stream(request: Request):
    queue = asyncio.Queue()
    state.sse_clients.append(queue)

    async def event_generator():
        try:
            yield f"data: {json.dumps(_full_state_dict())}\n\n"
            while True:
                get_task = asyncio.ensure_future(queue.get())
                disconnect_task = asyncio.ensure_future(request.is_disconnected())
                done, pending = await asyncio.wait(
                    {get_task, disconnect_task},
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=30.0,
                )
                for t in pending:
                    t.cancel()
                if disconnect_task in done and disconnect_task.result():
                    break
                if get_task in done:
                    yield f"data: {get_task.result()}\n\n"
                else:
                    yield ": keepalive\n\n"
        finally:
            state.sse_clients.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


class LoopbackStartRequest(BaseModel):
    mode: str = "virtual-sink"
    sink: str | None = None


async def _kill_playback(preserve_metadata=False):
    """Stop the current playback process and reset playback state."""
    if state.playback_process:
        handle = state.playback_process
        state.playback_process = None
        await handle.kill()
        if not preserve_metadata:
            state.current_file = None
            state.playback_duration = 0.0
            state.playback_started_at = 0.0
            state.playback_speed = 1.0
            state.playback_position = 0.0
            state.current_filepath = None


def _playback_kwargs():
    """Common kwargs forwarded to backend.start_playback."""
    return {"sample_rate": config["sample_rate"], "channels": config["channels"]}


async def _start_playback_pipeline(filepath, position, speed):
    """Launch the playback pipeline with seek and speed."""
    state.playback_process = await backend.start_playback(
        filepath, config["virtual_sink_name"], position, speed,
        **_playback_kwargs(),
    )
    state.playback_started_at = time.time()
    asyncio.create_task(_monitor_playback(state.playback_process))


@app.post("/api/loopback/start")
async def start_loopback(req: LoopbackStartRequest):
    if state.loopback_running:
        return {"error": "Loopback already running"}

    # Mutual exclusion: stop conversation if running
    if conv_state.running:
        if conv_state._task:
            conv_state._task.cancel()
            try:
                await conv_state._task
            except asyncio.CancelledError:
                pass
        await _stop_conversation_cleanup()

    if req.mode == "virtual-sink":
        log.info("Starting loopback: virtual-sink mode")
        state.loopback_process = await backend.create_virtual_sink(
            config["virtual_sink_name"], "Virtual Sink",
            config["virtual_mic_name"], "Virtual Mic",
        )
    elif req.mode == "sink-capture":
        if not req.sink:
            return {"error": "sink required for sink-capture mode"}
        log.info("Starting loopback: sink-capture mode, sink=%s", req.sink)
        state.loopback_process = await backend.create_virtual_sink(
            None, None,
            config["virtual_mic_name"], "Virtual Mic",
            capture_target=req.sink,
        )
    else:
        return {"error": f"Unknown mode: {req.mode}"}

    state.loopback_running = True
    state.loopback_mode = req.mode
    await broadcast_state()
    log.info("Loopback started (%s)", req.mode)
    return {"status": "started", "mode": req.mode}


@app.post("/api/loopback/stop")
async def stop_loopback():
    if not state.loopback_running:
        return {"error": "Loopback not running"}

    log.info("Stopping loopback")
    await _kill_playback()

    await backend.destroy_virtual_sink(state.loopback_process)
    state.loopback_process = None
    state.loopback_running = False
    await broadcast_state()
    log.info("Loopback stopped")
    return {"status": "stopped"}


class PlayRequest(BaseModel):
    filename: str


@app.post("/api/play")
async def play_file(req: PlayRequest):
    if not state.loopback_running or state.loopback_mode != "virtual-sink":
        return {"error": "Loopback must be running in virtual-sink mode"}

    samples = _samples_dir()
    filepath = (samples / req.filename).resolve()
    if not filepath.is_relative_to(samples.resolve()):
        return {"error": "Invalid filename"}
    if not filepath.is_file():
        return {"error": "File not found"}

    await _kill_playback()

    state.playback_duration = await backend.get_duration(filepath)
    state.playback_speed = 1.0
    state.playback_position = 0.0
    state.current_filepath = str(filepath)

    log.info("Playing %s (%.1fs)", req.filename, state.playback_duration)
    await _start_playback_pipeline(filepath, 0, state.playback_speed)
    state.current_file = req.filename
    await broadcast_state()

    return {"status": "playing", "filename": req.filename}


async def _monitor_playback(handle):
    await handle.wait()
    if state.playback_process is handle:
        state.playback_process = None
        state.current_file = None
        state.playback_duration = 0.0
        state.playback_started_at = 0.0
        state.playback_speed = 1.0
        state.playback_position = 0.0
        state.current_filepath = None
        await broadcast_state()


@app.post("/api/stop")
async def stop_playback():
    if not state.playback_process:
        return {"error": "Nothing playing"}

    await _kill_playback()
    await broadcast_state()
    return {"status": "stopped"}


class SpeedRequest(BaseModel):
    speed: float


@app.post("/api/speed")
async def set_speed(req: SpeedRequest):
    allowed = set(config["allowed_speeds"])
    if req.speed not in allowed:
        return {"error": f"Invalid speed. Allowed: {sorted(allowed)}"}

    old_speed = state.playback_speed
    state.playback_speed = req.speed

    if not state.playback_process:
        await broadcast_state()
        return {"status": "ok", "speed": req.speed}

    pos = state.playback_position + (time.time() - state.playback_started_at) * old_speed

    if pos >= state.playback_duration:
        await _kill_playback()
        await broadcast_state()
        return {"status": "stopped"}

    await _kill_playback(preserve_metadata=True)

    state.playback_position = pos
    await _start_playback_pipeline(state.current_filepath, pos, req.speed)
    await broadcast_state()
    return {"status": "ok", "speed": req.speed}


class VolumeRequest(BaseModel):
    percent: int


@app.post("/api/volume")
async def set_volume(req: VolumeRequest):
    await backend.set_source_volume(config["virtual_mic_name"], req.percent)
    state.volume = req.percent
    await broadcast_state()
    return {"status": "ok", "percent": req.percent}


class ConversationStartRequest(BaseModel):
    script: str


async def _stop_conversation_cleanup(release_loopbacks: bool = True):
    """Tear down playback and optionally the loopbacks too."""
    if conv_state.playback_process:
        await conv_state.playback_process.kill()

    if release_loopbacks:
        await backend.destroy_virtual_sink(conv_state.loopback1_process)
        await backend.destroy_virtual_sink(conv_state.loopback2_process)
        conv_state.__init__()
    else:
        conv_state.playback_process = None
        conv_state.running = False
        conv_state.script = None
        conv_state.turns = []
        conv_state.current_turn = -1
        conv_state.gap_min = config["conversation_gap_min"]
        conv_state.gap_max = config["conversation_gap_max"]
        conv_state.playback_duration = 0.0
        conv_state.playback_started_at = 0.0
        conv_state._task = None


async def _start_conversation_loopbacks():
    """Start conversation virtual sinks 1 and 2."""
    log.info("Creating conversation loopbacks (VirtualSink1/2, VirtualMic1/2)")
    conv_state.loopback1_process = await backend.create_virtual_sink(
        config.conversation_sink_name(1), "Virtual Sink 1",
        config.conversation_mic_name(1), "Virtual Mic 1",
        passive=True,
    )
    conv_state.loopback2_process = await backend.create_virtual_sink(
        config.conversation_sink_name(2), "Virtual Sink 2",
        config.conversation_mic_name(2), "Virtual Mic 2",
        passive=True,
    )
    conv_state.loopbacks_ready = True


async def _run_conversation():
    """Background task that plays conversation turns sequentially."""
    total = len(conv_state.turns)
    log.info("Conversation started: %s (%d turns)", conv_state.script, total)
    try:
        for i, turn in enumerate(conv_state.turns):
            conv_state.current_turn = i
            speaker = turn["speaker"]
            sink = config.conversation_sink_name(speaker)
            filepath = _samples_dir() / turn["file"]

            conv_state.playback_duration = await backend.get_duration(filepath)

            log.info("Turn %d/%d: speaker %d → %s (%.1fs)",
                     i + 1, total, speaker, turn["file"], conv_state.playback_duration)

            conv_state.playback_process = await backend.start_playback(
                filepath, sink, 0, 1.0,
                **_playback_kwargs(),
            )
            conv_state.playback_started_at = time.time()
            await broadcast_state()

            returncode = await conv_state.playback_process.wait()
            conv_state.playback_process = None

            if returncode != 0:
                log.error("Turn %d/%d playback failed (exit %d)", i + 1, total, returncode)
                await _stop_conversation_cleanup()
                await broadcast_state()
                return

            if i < len(conv_state.turns) - 1:
                gap = random.uniform(conv_state.gap_min, conv_state.gap_max)
                log.debug("Gap before next turn: %.2fs", gap)
                await asyncio.sleep(gap)

        log.info("Conversation finished: %s", conv_state.script)
        await _stop_conversation_cleanup(release_loopbacks=False)
        await broadcast_state()
    except asyncio.CancelledError:
        log.info("Conversation cancelled")


@app.post("/api/conversation/start")
async def start_conversation(req: ConversationStartRequest):
    if conv_state.running:
        return {"error": "Conversation already running"}

    samples = _samples_dir()
    conv_dir = samples / "conversations"
    script_path = (conv_dir / req.script).resolve()
    if not script_path.is_relative_to(conv_dir.resolve()):
        return {"error": "Invalid script path"}
    if not script_path.is_file():
        return {"error": "Script not found"}

    try:
        script_data = json.loads(script_path.read_text())
    except json.JSONDecodeError:
        return {"error": "Invalid JSON in script"}

    turns = script_data.get("turns")
    if not isinstance(turns, list) or len(turns) == 0:
        return {"error": "Script must contain a non-empty 'turns' array"}

    for i, turn in enumerate(turns):
        if turn.get("speaker") not in (1, 2):
            return {"error": f"Turn {i}: speaker must be 1 or 2"}
        if not isinstance(turn.get("file"), str):
            return {"error": f"Turn {i}: file must be a string"}
        if not (samples / turn["file"]).is_file():
            return {"error": f"Turn {i}: file not found: {turn['file']}"}

    gap_min = script_data.get("gap_min", script_data.get("gap", config["conversation_gap_min"]))
    gap_max = script_data.get("gap_max", script_data.get("gap", config["conversation_gap_max"]))

    if state.loopback_running:
        await _kill_playback()
        await backend.destroy_virtual_sink(state.loopback_process)
        state.loopback_process = None
        state.loopback_running = False

    if not conv_state.loopbacks_ready:
        await _start_conversation_loopbacks()

    conv_state.running = True
    conv_state.script = req.script
    conv_state.turns = turns
    conv_state.gap_min = gap_min
    conv_state.gap_max = gap_max
    conv_state.current_turn = -1
    conv_state._task = asyncio.create_task(_run_conversation())

    await broadcast_state()
    return {"status": "started", "script": req.script}


@app.post("/api/conversation/stop")
async def stop_conversation():
    if not conv_state.running:
        return {"error": "No conversation running"}

    if conv_state._task:
        conv_state._task.cancel()
        try:
            await conv_state._task
        except asyncio.CancelledError:
            pass

    await _stop_conversation_cleanup(release_loopbacks=False)
    await broadcast_state()
    return {"status": "stopped"}


@app.post("/api/conversation/prepare")
async def prepare_conversation():
    if conv_state.loopbacks_ready:
        return {"status": "already_ready"}

    if conv_state.running:
        return {"error": "Conversation already running"}

    if state.loopback_running:
        await _kill_playback()
        await backend.destroy_virtual_sink(state.loopback_process)
        state.loopback_process = None
        state.loopback_running = False

    await _start_conversation_loopbacks()
    await broadcast_state()
    return {"status": "ready"}


@app.post("/api/conversation/unprepare")
async def unprepare_conversation():
    if conv_state.running:
        return {"error": "Stop the conversation before releasing mics"}
    if not conv_state.loopbacks_ready:
        return {"error": "Mics not prepared"}

    await _stop_conversation_cleanup(release_loopbacks=True)
    await broadcast_state()
    return {"status": "released"}


@app.get("/api/conversations")
async def list_conversations():
    conv_dir = _samples_dir() / "conversations"
    if not conv_dir.is_dir():
        return {"conversations": []}
    scripts = sorted(
        f.name for f in conv_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".json"
    )
    return {"conversations": scripts}


@app.get("/api/conversations/{name}/transcript")
async def get_conversation_transcript(name: str):
    """Return transcript.json for a conversation if it exists."""
    samples = _samples_dir()
    transcript_path = samples / "conversations" / name / "transcript.json"
    if not transcript_path.is_file():
        return {"turns": []}
    try:
        data = json.loads(transcript_path.read_text())
        return data
    except json.JSONDecodeError:
        return {"turns": []}


@app.get("/api/capabilities")
async def capabilities():
    return {
        "platform": platform.system(),
        "supports_dynamic_device_creation": backend.supports_dynamic_device_creation,
        "virtual_cables": await backend.list_virtual_cables(),
    }


@app.get("/api/config")
async def get_config():
    return config.to_dict()


@app.put("/api/config")
async def update_config(request: Request):
    body = await request.json()
    errors = config.update(body)
    if errors:
        return {"errors": errors}
    return config.to_dict()


# --- Generation endpoints ---


class GenerateTranscriptRequest(BaseModel):
    topic: str
    speakers: list[str] | None = None


@app.post("/api/generate/transcript")
async def generate_transcript(req: GenerateTranscriptRequest):
    if not shutil.which("claude"):
        return {"error": "claude CLI not found on PATH"}

    speaker_part = ""
    if req.speakers:
        names = ", ".join(req.speakers)
        speaker_part = f" The speakers are: {names}."

    prompt = (
        f"Generate a realistic conversation about: {req.topic}.{speaker_part} "
        f"Output ONLY the dialogue, one turn per line, in this exact format:\n"
        f"SpeakerName: What they say\n\n"
        f"Do not include stage directions, scene descriptions, or any other text. "
        f"Just the dialogue lines. Use exactly 2 speakers unless more were specified."
    )

    log.info("Generating transcript via claude CLI: topic=%r", req.topic)
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def stream():
        try:
            async for chunk in proc.stdout:
                text = chunk.decode("utf-8", errors="replace")
                yield f"data: {json.dumps({'text': text})}\n\n"
            await proc.wait()
            if proc.returncode != 0:
                stderr = (await proc.stderr.read()).decode("utf-8", errors="replace")
                log.error("claude CLI failed (exit %d): %s", proc.returncode, stderr[:200])
                yield f"data: {json.dumps({'error': stderr or 'claude exited with error'})}\n\n"
            else:
                log.info("claude CLI transcript generation complete")
            yield f"data: {json.dumps({'done': True})}\n\n"
        except asyncio.CancelledError:
            proc.kill()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


class ParseTranscriptRequest(BaseModel):
    text: str


@app.post("/api/generate/parse")
async def generate_parse(req: ParseTranscriptRequest):
    turns = parse_transcript(req.text)
    if not turns:
        return {"error": "No valid turns found. Use format: SpeakerName: text"}
    speakers = unique_speakers(turns)
    return {"speakers": speakers, "turns": turns}


class GenerateTTSRequest(BaseModel):
    name: str
    turns: list[dict]
    speaker_mapping: dict[str, int]
    provider: str = "elevenlabs"
    speed: float = 1.2
    gap_min: float = 0.1
    gap_max: float = 1.0
    overwrite: bool = False


@app.post("/api/generate/tts")
async def generate_tts(req: GenerateTTSRequest):
    if gen_state.active:
        return {"error": "Generation already in progress"}

    samples = _samples_dir()
    conv_dir = samples / "conversations" / req.name
    script_path = samples / "conversations" / f"{req.name}.json"

    if conv_dir.exists() and not req.overwrite:
        return {"error": f"Conversation '{req.name}' already exists. Set overwrite=true to replace."}

    # Validate speaker mapping
    speakers = unique_speakers(req.turns)
    for s in speakers:
        if s not in req.speaker_mapping:
            return {"error": f"Speaker '{s}' missing from speaker_mapping"}
        if req.speaker_mapping[s] not in (1, 2):
            return {"error": f"Speaker '{s}' must be mapped to 1 or 2"}

    try:
        provider = get_tts_provider(req.provider)
    except ValueError as e:
        return {"error": str(e)}

    # Assign speaker numbers and voices
    try:
        turns_with_nums = assign_speaker_numbers(req.turns, req.speaker_mapping)
    except ValueError as e:
        return {"error": str(e)}

    voice_map = assign_voices(speakers, req.provider)

    gen_state.active = True
    gen_state.step = "tts"
    gen_state.tts_total = len(turns_with_nums)
    gen_state.tts_completed = 0
    gen_state.error = None
    gen_state.conversation_name = req.name

    log.info("Starting TTS generation: name=%r, provider=%s, %d turns", req.name, req.provider, len(turns_with_nums))
    for name, voice_id in voice_map.items():
        log.info("  Voice: %s → %s", name, voice_id)

    async def run_tts():
        try:
            conv_dir.mkdir(parents=True, exist_ok=True)

            for i, turn in enumerate(turns_with_nums, start=1):
                speaker = turn["speaker"]
                voice = voice_map[speaker]
                safe_name = speaker.lower().replace(" ", "_")
                filename = f"turn_{i:03d}_{safe_name}.mp3"
                filepath = conv_dir / filename

                log.info("TTS %d/%d: %s — %s", i, len(turns_with_nums), speaker, turn["text"][:60])
                audio_bytes = await provider.synthesize(turn["text"], voice, req.speed)
                filepath.write_bytes(audio_bytes)
                log.info("TTS %d/%d: wrote %s (%d bytes)", i, len(turns_with_nums), filename, len(audio_bytes))

                gen_state.tts_completed = i
                await broadcast_state()

            # Write turns JSON
            turns_json = build_turns_json(req.name, turns_with_nums, req.gap_min, req.gap_max)
            script_path.write_text(json.dumps(turns_json, indent=2))

            # Write transcript JSON
            transcript_json = build_transcript_json(turns_with_nums)
            (conv_dir / "transcript.json").write_text(json.dumps(transcript_json, indent=2))

            log.info("TTS generation complete: %s (%d turns)", req.name, len(turns_with_nums))
            gen_state.active = False
            gen_state.step = None
            await broadcast_state()
        except asyncio.CancelledError:
            log.info("TTS generation cancelled: %s", req.name)
            gen_state.active = False
            gen_state.step = None
            gen_state.error = "Cancelled"
            await broadcast_state()
        except Exception as e:
            log.error("TTS generation failed: %s", e)
            gen_state.active = False
            gen_state.step = None
            gen_state.error = str(e)
            await broadcast_state()

    gen_state._task = asyncio.create_task(run_tts())
    await broadcast_state()
    return {"status": "started", "total_turns": len(turns_with_nums)}


@app.post("/api/generate/cancel")
async def generate_cancel():
    if not gen_state.active:
        return {"error": "No generation in progress"}
    if gen_state._task:
        gen_state._task.cancel()
        try:
            await gen_state._task
        except asyncio.CancelledError:
            pass
    gen_state.active = False
    gen_state.step = None
    gen_state.error = "Cancelled"
    gen_state._task = None
    await broadcast_state()
    return {"status": "cancelled"}


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
