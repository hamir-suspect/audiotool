# Conversation Mock Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a conversation mode that creates two virtual microphones and plays a scripted sequence of audio files through them in alternating turns.

**Architecture:** A new `ConversationState` alongside existing `AppState` manages two pw-loopback processes and a background asyncio task that walks through a JSON script turn-by-turn. The two modes are mutually exclusive. The frontend toggles between single-mic and conversation UI based on SSE state.

**Tech Stack:** Python/FastAPI backend, vanilla JS frontend, PipeWire pw-loopback, ffmpeg/paplay pipeline.

---

### Task 1: Add ConversationState and Wire Into SSE

**Files:**
- Modify: `app.py:20-54` (add ConversationState class, update broadcast)
- Modify: `tests/test_app.py:22-27` (update reset_state fixture)
- Modify: `tests/test_app.py:64-99` (update SSE test)

- [ ] **Step 1: Write test for conversation fields in SSE initial state**

Add to the bottom of the existing SSE test in `tests/test_app.py`. The test already exists at line 64 — extend its assertions:

```python
@pytest.mark.anyio
async def test_status_sse_includes_conversation_fields():
    """SSE initial state includes conversation fields."""
    from unittest.mock import MagicMock
    from fastapi import Request
    from app import status_stream

    call_count = 0

    async def is_disconnected():
        nonlocal call_count
        call_count += 1
        return call_count > 1

    mock_request = MagicMock(spec=Request)
    mock_request.is_disconnected = is_disconnected

    response = await status_stream(mock_request)
    first_event = None
    async for chunk in response.body_iterator:
        if chunk.startswith("data: "):
            first_event = chunk
            break

    data = json.loads(first_event[6:].strip())
    assert data["conversation_running"] is False
    assert data["conversation_script"] is None
    assert data["conversation_turns"] == []
    assert data["conversation_current_turn"] == -1
    assert data["conversation_gap"] == 1.0
    assert data["conversation_playback_duration"] == 0
    assert data["conversation_playback_started_at"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_app.py::test_status_sse_includes_conversation_fields -v`
Expected: FAIL — `conversation_running` key not present in SSE data.

- [ ] **Step 3: Implement ConversationState and wire into broadcast**

In `app.py`, after the `AppState` class (after line 46), add:

```python
class ConversationState:
    def __init__(self):
        self.running = False
        self.script = None
        self.turns = []
        self.current_turn = -1
        self.gap = 1.0
        self.loopback1_process = None
        self.loopback2_process = None
        self.playback_process = None
        self.playback_duration = 0.0
        self.playback_started_at = 0.0
        self._task = None

    def to_dict(self):
        return {
            "conversation_running": self.running,
            "conversation_script": self.script,
            "conversation_turns": self.turns,
            "conversation_current_turn": self.current_turn,
            "conversation_gap": self.gap,
            "conversation_playback_duration": self.playback_duration,
            "conversation_playback_started_at": self.playback_started_at,
        }


conv_state = ConversationState()
```

Replace the `broadcast_state` function and add a helper:

```python
def _full_state_dict():
    d = state.to_dict()
    d.update(conv_state.to_dict())
    return d


async def broadcast_state():
    data = json.dumps(_full_state_dict())
    for queue in list(state.sse_clients):
        await queue.put(data)
```

Update the SSE initial event in `status_stream` (line 97) to use `_full_state_dict()`:

```python
yield f"data: {json.dumps(_full_state_dict())}\n\n"
```

Update `reset_state` fixture in `tests/test_app.py` to also reset conversation state:

```python
@pytest.fixture(autouse=True)
def reset_state():
    from app import state, conv_state
    state.__init__()
    conv_state.__init__()
    yield
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_app.py -v`
Expected: ALL PASS (new test + all existing tests).

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: add ConversationState and wire into SSE broadcast"
```

---

### Task 2: List Conversation Scripts Endpoint

**Files:**
- Modify: `app.py` (add `/api/conversations` endpoint)
- Modify: `tests/test_app.py` (add tests)

- [ ] **Step 1: Write tests for listing conversation scripts**

Add to `tests/test_app.py`:

```python
def test_list_conversations(samples_dir, client):
    conv_dir = samples_dir / "conversations"
    conv_dir.mkdir()
    (conv_dir / "chat.json").write_text('{"turns": []}')
    (conv_dir / "demo.json").write_text('{"turns": []}')
    (conv_dir / "readme.txt").touch()

    resp = client.get("/api/conversations")
    assert resp.status_code == 200
    assert resp.json()["conversations"] == ["chat.json", "demo.json"]


def test_list_conversations_no_dir(samples_dir, client):
    resp = client.get("/api/conversations")
    assert resp.status_code == 200
    assert resp.json()["conversations"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_app.py::test_list_conversations tests/test_app.py::test_list_conversations_no_dir -v`
Expected: FAIL — 404 (endpoint doesn't exist).

- [ ] **Step 3: Implement the endpoint**

Add to `app.py`, before the `app.mount` line at the bottom:

```python
@app.get("/api/conversations")
async def list_conversations():
    conv_dir = SAMPLES_DIR / "conversations"
    if not conv_dir.is_dir():
        return {"conversations": []}
    scripts = sorted(
        f.name for f in conv_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".json"
    )
    return {"conversations": scripts}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_app.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: add GET /api/conversations endpoint"
```

---

### Task 3: Conversation Start With Validation

**Files:**
- Modify: `app.py` (add `/api/conversation/start` endpoint with validation + loopback creation)
- Modify: `tests/test_app.py` (add validation + start tests)

- [ ] **Step 1: Write validation tests**

Add to `tests/test_app.py`:

```python
def test_conversation_start_script_not_found(samples_dir, client):
    conv_dir = samples_dir / "conversations"
    conv_dir.mkdir()

    resp = client.post("/api/conversation/start", json={"script": "missing.json"})
    assert "error" in resp.json()
    assert "not found" in resp.json()["error"].lower()


def test_conversation_start_invalid_json(samples_dir, client):
    conv_dir = samples_dir / "conversations"
    conv_dir.mkdir()
    (conv_dir / "bad.json").write_text("not json{{{")

    resp = client.post("/api/conversation/start", json={"script": "bad.json"})
    assert "error" in resp.json()


def test_conversation_start_missing_turns(samples_dir, client):
    conv_dir = samples_dir / "conversations"
    conv_dir.mkdir()
    (conv_dir / "empty.json").write_text('{"gap": 1.0}')

    resp = client.post("/api/conversation/start", json={"script": "empty.json"})
    assert "error" in resp.json()


def test_conversation_start_invalid_speaker(samples_dir, client):
    conv_dir = samples_dir / "conversations"
    conv_dir.mkdir()
    script = {"turns": [{"speaker": 3, "file": "a.mp3"}]}
    (conv_dir / "bad_speaker.json").write_text(json.dumps(script))
    (samples_dir / "a.mp3").touch()

    resp = client.post("/api/conversation/start", json={"script": "bad_speaker.json"})
    assert "error" in resp.json()
    assert "speaker" in resp.json()["error"].lower()


def test_conversation_start_audio_file_missing(samples_dir, client):
    conv_dir = samples_dir / "conversations"
    conv_dir.mkdir()
    script = {"turns": [{"speaker": 1, "file": "nonexistent.mp3"}]}
    (conv_dir / "missing_audio.json").write_text(json.dumps(script))

    resp = client.post("/api/conversation/start", json={"script": "missing_audio.json"})
    assert "error" in resp.json()
    assert "not found" in resp.json()["error"].lower()


def test_conversation_start_empty_turns(samples_dir, client):
    conv_dir = samples_dir / "conversations"
    conv_dir.mkdir()
    (conv_dir / "empty_turns.json").write_text('{"turns": []}')

    resp = client.post("/api/conversation/start", json={"script": "empty_turns.json"})
    assert "error" in resp.json()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_app.py::test_conversation_start_script_not_found tests/test_app.py::test_conversation_start_invalid_json tests/test_app.py::test_conversation_start_missing_turns tests/test_app.py::test_conversation_start_invalid_speaker tests/test_app.py::test_conversation_start_audio_file_missing tests/test_app.py::test_conversation_start_empty_turns -v`
Expected: FAIL — 404 or 422 (endpoint doesn't exist).

- [ ] **Step 3: Write test for successful conversation start**

Add to `tests/test_app.py`:

```python
def test_conversation_start_success(samples_dir, client):
    conv_dir = samples_dir / "conversations"
    conv_dir.mkdir()
    (samples_dir / "hello.mp3").write_bytes(b"fake")
    (samples_dir / "reply.mp3").write_bytes(b"fake")
    script = {
        "gap": 1.5,
        "turns": [
            {"speaker": 1, "file": "hello.mp3"},
            {"speaker": 2, "file": "reply.mp3"},
        ],
    }
    (conv_dir / "chat.json").write_text(json.dumps(script))

    mock_loopback = MagicMock()
    mock_loopback.wait = AsyncMock()
    mock_duration = MagicMock()
    mock_duration.communicate = AsyncMock(return_value=(b"10.0", b""))
    mock_play = MagicMock()
    mock_play.wait = AsyncMock()
    mock_play.pid = 12345

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_loopback) as mock_exec, \
         patch("asyncio.create_subprocess_shell", new_callable=AsyncMock, return_value=mock_play):
        # Mock create_subprocess_exec to return loopback procs first, then duration proc
        mock_exec.side_effect = [mock_loopback, mock_loopback, mock_duration]
        resp = client.post("/api/conversation/start", json={"script": "chat.json"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"

    from app import conv_state
    assert conv_state.running is True
    assert conv_state.script == "chat.json"
    assert conv_state.gap == 1.5
    assert len(conv_state.turns) == 2
```

- [ ] **Step 4: Run new test to verify it fails**

Run: `python3 -m pytest tests/test_app.py::test_conversation_start_success -v`
Expected: FAIL — endpoint doesn't exist.

- [ ] **Step 5: Implement the endpoint**

Add to `app.py`, before the `app.mount` line:

```python
class ConversationStartRequest(BaseModel):
    script: str


@app.post("/api/conversation/start")
async def start_conversation(req: ConversationStartRequest):
    if conv_state.running:
        return {"error": "Conversation already running"}

    # Validate script file
    conv_dir = SAMPLES_DIR / "conversations"
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
        if not (SAMPLES_DIR / turn["file"]).is_file():
            return {"error": f"Turn {i}: file not found: {turn['file']}"}

    gap = script_data.get("gap", 1.0)

    # Mutual exclusion: stop single-mic if running
    if state.loopback_running:
        await _kill_playback()
        state.loopback_process.terminate()
        await state.loopback_process.wait()
        state.loopback_process = None
        state.loopback_running = False

    # Start two loopbacks
    conv_state.loopback1_process = await asyncio.create_subprocess_exec(
        "pw-loopback",
        '--capture-props=media.class=Audio/Sink node.name=VirtualSink1 node.description="Virtual Sink 1"',
        '--playback-props=media.class=Audio/Source node.name=VirtualMic1 node.description="Virtual Mic 1"',
    )
    conv_state.loopback2_process = await asyncio.create_subprocess_exec(
        "pw-loopback",
        '--capture-props=media.class=Audio/Sink node.name=VirtualSink2 node.description="Virtual Sink 2"',
        '--playback-props=media.class=Audio/Source node.name=VirtualMic2 node.description="Virtual Mic 2"',
    )

    conv_state.running = True
    conv_state.script = req.script
    conv_state.turns = turns
    conv_state.gap = gap
    conv_state.current_turn = -1

    # Start background turn execution
    conv_state._task = asyncio.create_task(_run_conversation())

    await broadcast_state()
    return {"status": "started", "script": req.script}
```

Also add a stub for `_run_conversation` so the task doesn't crash (full implementation in Task 4):

```python
async def _run_conversation():
    """Background task that plays conversation turns. Implemented in Task 4."""
    pass
```

- [ ] **Step 6: Run all tests to verify they pass**

Run: `python3 -m pytest tests/test_app.py -v`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: add POST /api/conversation/start with validation"
```

---

### Task 4: Turn Execution Background Task

**Files:**
- Modify: `app.py` (implement `_run_conversation` and `_stop_conversation_cleanup`)
- Modify: `tests/test_app.py` (add turn execution and completion tests)

- [ ] **Step 1: Write test for turn execution**

Add to `tests/test_app.py`:

```python
@pytest.mark.anyio
async def test_conversation_turn_execution(samples_dir):
    """Background task plays turns in sequence on correct sinks."""
    from app import conv_state, _run_conversation, SAMPLES_DIR
    import app as app_module

    (samples_dir / "a.mp3").write_bytes(b"fake")
    (samples_dir / "b.mp3").write_bytes(b"fake")

    conv_state.running = True
    conv_state.script = "test.json"
    conv_state.turns = [
        {"speaker": 1, "file": "a.mp3"},
        {"speaker": 2, "file": "b.mp3"},
    ]
    conv_state.gap = 0.0  # no gap for fast test
    conv_state.loopback1_process = MagicMock()
    conv_state.loopback1_process.terminate = MagicMock()
    conv_state.loopback1_process.wait = AsyncMock()
    conv_state.loopback2_process = MagicMock()
    conv_state.loopback2_process.terminate = MagicMock()
    conv_state.loopback2_process.wait = AsyncMock()

    mock_duration = MagicMock()
    mock_duration.communicate = AsyncMock(return_value=(b"5.0", b""))

    mock_play = MagicMock()
    mock_play.wait = AsyncMock()
    mock_play.pid = 12345

    shell_calls = []

    async def mock_shell(cmd, **kwargs):
        shell_calls.append(cmd)
        return mock_play

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_duration), \
         patch("asyncio.create_subprocess_shell", side_effect=mock_shell):
        await _run_conversation()

    # Should have played two turns
    assert len(shell_calls) == 2
    assert "VirtualSink1" in shell_calls[0]
    assert "VirtualSink2" in shell_calls[1]

    # Should be cleaned up after completion
    assert conv_state.running is False
    assert conv_state.current_turn == -1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_app.py::test_conversation_turn_execution -v`
Expected: FAIL — `_run_conversation` is a stub that does nothing.

- [ ] **Step 3: Write test for conversation completion cleanup**

Add to `tests/test_app.py`:

```python
@pytest.mark.anyio
async def test_conversation_completion_tears_down_loopbacks(samples_dir):
    """When all turns complete, loopbacks are terminated."""
    from app import conv_state, _run_conversation

    (samples_dir / "a.mp3").write_bytes(b"fake")

    conv_state.running = True
    conv_state.turns = [{"speaker": 1, "file": "a.mp3"}]
    conv_state.gap = 0.0

    mock_lb1 = MagicMock()
    mock_lb1.terminate = MagicMock()
    mock_lb1.wait = AsyncMock()
    mock_lb2 = MagicMock()
    mock_lb2.terminate = MagicMock()
    mock_lb2.wait = AsyncMock()
    conv_state.loopback1_process = mock_lb1
    conv_state.loopback2_process = mock_lb2

    mock_duration = MagicMock()
    mock_duration.communicate = AsyncMock(return_value=(b"5.0", b""))
    mock_play = MagicMock()
    mock_play.wait = AsyncMock()
    mock_play.pid = 12345

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_duration), \
         patch("asyncio.create_subprocess_shell", new_callable=AsyncMock, return_value=mock_play):
        await _run_conversation()

    mock_lb1.terminate.assert_called_once()
    mock_lb2.terminate.assert_called_once()
    assert conv_state.loopback1_process is None
    assert conv_state.loopback2_process is None
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python3 -m pytest tests/test_app.py::test_conversation_completion_tears_down_loopbacks -v`
Expected: FAIL.

- [ ] **Step 5: Implement _run_conversation and _stop_conversation_cleanup**

Replace the `_run_conversation` stub in `app.py` with:

```python
async def _stop_conversation_cleanup():
    """Tear down loopbacks and reset conversation state."""
    if conv_state.playback_process:
        try:
            os.killpg(os.getpgid(conv_state.playback_process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        await conv_state.playback_process.wait()

    for proc in [conv_state.loopback1_process, conv_state.loopback2_process]:
        if proc:
            proc.terminate()
            await proc.wait()

    conv_state.__init__()


async def _run_conversation():
    """Background task that plays conversation turns sequentially."""
    try:
        for i, turn in enumerate(conv_state.turns):
            conv_state.current_turn = i
            speaker = turn["speaker"]
            sink = f"VirtualSink{speaker}"
            filepath = SAMPLES_DIR / turn["file"]

            # Get duration via ffprobe
            duration_proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(filepath),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await duration_proc.communicate()
            try:
                conv_state.playback_duration = float(stdout.decode().strip())
            except ValueError:
                conv_state.playback_duration = 0.0

            # Start ffmpeg | paplay pipeline
            cmd = (
                f"ffmpeg -i {shlex.quote(str(filepath))} "
                f"-f wav -ac 2 -ar 48000 - 2>/dev/null "
                f"| paplay --device={sink}"
            )
            conv_state.playback_process = await asyncio.create_subprocess_shell(
                cmd, start_new_session=True,
            )
            conv_state.playback_started_at = time.time()
            await broadcast_state()

            # Wait for turn to finish
            returncode = await conv_state.playback_process.wait()
            conv_state.playback_process = None

            # Fail explicitly on playback error
            if returncode != 0:
                await _stop_conversation_cleanup()
                await broadcast_state()
                return

            # Gap between turns (skip after last turn)
            if i < len(conv_state.turns) - 1:
                await asyncio.sleep(conv_state.gap)

        # All turns complete — clean up
        await _stop_conversation_cleanup()
        await broadcast_state()
    except asyncio.CancelledError:
        pass
```

- [ ] **Step 6: Run all tests to verify they pass**

Run: `python3 -m pytest tests/test_app.py -v`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: implement turn execution background task with cleanup"
```

---

### Task 5: Stop Conversation Endpoint

**Files:**
- Modify: `app.py` (add `/api/conversation/stop` endpoint)
- Modify: `tests/test_app.py` (add stop tests)

- [ ] **Step 1: Write tests for stop conversation**

Add to `tests/test_app.py`:

```python
@pytest.mark.anyio
async def test_conversation_stop():
    """Stop kills playback, loopbacks, and resets state."""
    from app import conv_state, stop_conversation

    mock_play = MagicMock()
    mock_play.wait = AsyncMock()
    mock_play.pid = 12345

    mock_lb1 = MagicMock()
    mock_lb1.terminate = MagicMock()
    mock_lb1.wait = AsyncMock()
    mock_lb2 = MagicMock()
    mock_lb2.terminate = MagicMock()
    mock_lb2.wait = AsyncMock()

    conv_state.running = True
    conv_state.script = "chat.json"
    conv_state.turns = [{"speaker": 1, "file": "a.mp3"}]
    conv_state.current_turn = 0
    conv_state.playback_process = mock_play
    conv_state.loopback1_process = mock_lb1
    conv_state.loopback2_process = mock_lb2
    conv_state._task = asyncio.create_task(asyncio.sleep(999))

    with patch("os.killpg"), patch("os.getpgid", return_value=12345):
        resp = await stop_conversation()

    assert resp["status"] == "stopped"
    assert conv_state.running is False
    assert conv_state.playback_process is None
    assert conv_state.loopback1_process is None
    mock_lb1.terminate.assert_called_once()
    mock_lb2.terminate.assert_called_once()


def test_conversation_stop_not_running(client):
    resp = client.post("/api/conversation/stop")
    assert "error" in resp.json()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_app.py::test_conversation_stop tests/test_app.py::test_conversation_stop_not_running -v`
Expected: FAIL — endpoint/function doesn't exist.

- [ ] **Step 3: Implement the endpoint**

Add to `app.py`, before the `app.mount` line:

```python
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

    await _stop_conversation_cleanup()
    await broadcast_state()
    return {"status": "stopped"}
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `python3 -m pytest tests/test_app.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: add POST /api/conversation/stop endpoint"
```

---

### Task 6: Mutual Exclusion

**Files:**
- Modify: `app.py:166-192` (update `start_loopback` to stop conversation first)
- Modify: `tests/test_app.py` (add mutual exclusion tests)

- [ ] **Step 1: Write test for starting single-mic while conversation running**

Add to `tests/test_app.py`:

```python
def test_start_loopback_stops_conversation(client):
    """Starting single-mic loopback stops any running conversation."""
    from app import conv_state

    mock_lb = MagicMock()
    mock_lb.terminate = MagicMock()
    mock_lb.wait = AsyncMock()

    conv_state.running = True
    conv_state.loopback1_process = mock_lb
    conv_state.loopback2_process = mock_lb
    conv_state._task = asyncio.create_task(asyncio.sleep(999))

    mock_new_lb = MagicMock()
    mock_new_lb.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_new_lb):
        resp = client.post("/api/loopback/start", json={"mode": "virtual-sink"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    assert conv_state.running is False
```

- [ ] **Step 2: Write test for starting conversation while single-mic running**

Add to `tests/test_app.py`:

```python
def test_start_conversation_stops_loopback(samples_dir, client):
    """Starting conversation stops any running single-mic loopback."""
    from app import state, conv_state

    conv_dir = samples_dir / "conversations"
    conv_dir.mkdir()
    (samples_dir / "a.mp3").write_bytes(b"fake")
    script = {"turns": [{"speaker": 1, "file": "a.mp3"}]}
    (conv_dir / "chat.json").write_text(json.dumps(script))

    mock_lb = MagicMock()
    mock_lb.terminate = MagicMock()
    mock_lb.wait = AsyncMock()
    state.loopback_running = True
    state.loopback_process = mock_lb

    mock_new_lb = MagicMock()
    mock_new_lb.wait = AsyncMock()
    mock_duration = MagicMock()
    mock_duration.communicate = AsyncMock(return_value=(b"5.0", b""))
    mock_play = MagicMock()
    mock_play.wait = AsyncMock()
    mock_play.pid = 12345

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec, \
         patch("asyncio.create_subprocess_shell", new_callable=AsyncMock, return_value=mock_play):
        mock_exec.side_effect = [mock_new_lb, mock_new_lb, mock_duration]
        resp = client.post("/api/conversation/start", json={"script": "chat.json"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    assert state.loopback_running is False
    mock_lb.terminate.assert_called_once()
```

- [ ] **Step 3: Run tests to verify start_loopback_stops_conversation fails**

Run: `python3 -m pytest tests/test_app.py::test_start_loopback_stops_conversation -v`
Expected: FAIL — `start_loopback` doesn't check for running conversation.

- [ ] **Step 4: Add mutual exclusion to start_loopback**

In `app.py`, at the top of the `start_loopback` function (after the `if state.loopback_running` check), add:

```python
    # Mutual exclusion: stop conversation if running
    if conv_state.running:
        if conv_state._task:
            conv_state._task.cancel()
            try:
                await conv_state._task
            except asyncio.CancelledError:
                pass
        await _stop_conversation_cleanup()
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `python3 -m pytest tests/test_app.py -v`
Expected: ALL PASS. The `test_start_conversation_stops_loopback` test should already pass because Task 3 included mutual exclusion in `start_conversation`.

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: add mutual exclusion between single-mic and conversation modes"
```

---

### Task 7: Frontend — HTML, CSS, and JavaScript

**Files:**
- Modify: `static/index.html` (add conversation section)
- Modify: `static/style.css` (add conversation styles)
- Modify: `static/app.js` (add conversation state, API functions, rendering)

- [ ] **Step 1: Add conversation section to HTML**

In `static/index.html`, add after the `<section id="audio-files">` closing tag (after line 43) and before the `<section id="now-playing">` (line 45):

```html
    <section id="conversation-control">
        <h2>Conversation Mode</h2>
        <div class="control-row">
            <select id="conversation-select"></select>
            <button id="btn-conv-start" onclick="startConversation()">Start Conversation</button>
        </div>
    </section>

    <section id="conversation-playing" style="display:none">
        <h2>Conversation</h2>
        <p id="conv-turn-info"></p>
        <p id="conv-speaker-info"></p>
        <p id="conv-file-info"></p>
        <div class="progress-container">
            <div id="conv-progress-bar" class="progress-bar"></div>
        </div>
        <span id="conv-progress-time">0:00 / 0:00</span>
        <div class="control-row" style="margin-top:0.5rem">
            <button onclick="stopConversation()">Stop Conversation</button>
        </div>
    </section>
```

- [ ] **Step 2: Add conversation styles**

Append to `static/style.css`:

```css

.speaker-indicator {
    font-weight: bold;
}

.speaker-1 {
    color: #4ecca3;
}

.speaker-2 {
    color: #e94560;
}
```

- [ ] **Step 3: Add conversation state and API functions to JS**

In `static/app.js`, extend the `state` object (line 1-10) to add conversation fields:

```javascript
const state = {
    loopback_running: false,
    loopback_mode: "virtual-sink",
    current_file: null,
    volume: 300,
    playback_duration: 0,
    playback_started_at: 0,
    playback_speed: 1.0,
    playback_position: 0,
    conversation_running: false,
    conversation_script: null,
    conversation_turns: [],
    conversation_current_turn: -1,
    conversation_gap: 1.0,
    conversation_playback_duration: 0,
    conversation_playback_started_at: 0,
};
```

Add API functions after the existing `setSpeed` function (after line 95):

```javascript
async function loadConversations() {
    const resp = await fetch("/api/conversations");
    const data = await resp.json();
    const select = document.getElementById("conversation-select");
    select.innerHTML = "";
    data.conversations.forEach((script) => {
        const option = document.createElement("option");
        option.value = script;
        option.textContent = script;
        select.appendChild(option);
    });
}

async function startConversation() {
    const script = document.getElementById("conversation-select").value;
    if (!script) return;
    await fetch("/api/conversation/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ script }),
    });
}

async function stopConversation() {
    await fetch("/api/conversation/stop", { method: "POST" });
}
```

- [ ] **Step 4: Update render function for conversation mode**

In the `render()` function in `static/app.js`, add conversation rendering at the end of the function (before the closing `}`):

```javascript
    // Conversation mode
    const convControl = document.getElementById("conversation-control");
    const convPlaying = document.getElementById("conversation-playing");

    if (state.conversation_running) {
        // Hide single-mic controls, show conversation
        document.getElementById("loopback-control").style.display = "none";
        document.getElementById("volume-control").style.display = "none";
        document.getElementById("audio-files").style.display = "none";
        nowPlaying.style.display = "none";
        convControl.style.display = "none";
        convPlaying.style.display = "block";

        const turn = state.conversation_current_turn;
        const total = state.conversation_turns.length;
        document.getElementById("conv-turn-info").textContent =
            `Turn ${turn + 1} of ${total}`;

        const speaker = state.conversation_turns[turn]?.speaker || "?";
        const speakerEl = document.getElementById("conv-speaker-info");
        speakerEl.textContent = `Speaker ${speaker}`;
        speakerEl.className = `speaker-indicator speaker-${speaker}`;

        const file = state.conversation_turns[turn]?.file || "";
        document.getElementById("conv-file-info").textContent = file;
    } else {
        // Show single-mic controls, hide conversation playing
        document.getElementById("loopback-control").style.display = "";
        document.getElementById("volume-control").style.display = "";
        document.getElementById("audio-files").style.display = "";
        convControl.style.display = "";
        convPlaying.style.display = "none";
    }
```

- [ ] **Step 5: Update progress bar interval for conversation mode**

In `static/app.js`, update the `setInterval` block (lines 201-215) to also handle conversation progress:

```javascript
setInterval(() => {
    if (state.current_file && state.playback_duration > 0) {
        const elapsed_in_source =
            state.playback_position +
            (Date.now() / 1000 - state.playback_started_at) * state.playback_speed;
        const progress = Math.min(
            (elapsed_in_source / state.playback_duration) * 100,
            100
        );
        document.getElementById("progress-bar").style.width = `${progress}%`;
        document.getElementById("progress-time").textContent = `${formatTime(
            elapsed_in_source
        )} / ${formatTime(state.playback_duration)}`;
    }
    if (state.conversation_running && state.conversation_playback_duration > 0) {
        const elapsed =
            (Date.now() / 1000 - state.conversation_playback_started_at);
        const progress = Math.min(
            (elapsed / state.conversation_playback_duration) * 100,
            100
        );
        document.getElementById("conv-progress-bar").style.width = `${progress}%`;
        document.getElementById("conv-progress-time").textContent = `${formatTime(
            elapsed
        )} / ${formatTime(state.conversation_playback_duration)}`;
    }
}, 500);
```

- [ ] **Step 6: Load conversations on startup**

In `static/app.js`, at the bottom (line 218), add alongside the existing `loadFiles()` call:

```javascript
loadFiles();
loadConversations();
```

- [ ] **Step 7: Manual test**

Verify in the browser at `http://localhost:8000`:
1. Conversation section appears with dropdown and "Start Conversation" button
2. When no conversation scripts exist, dropdown is empty
3. Create `SAMPLES_DIR/conversations/` and put a test JSON script in it, verify it shows in dropdown

- [ ] **Step 8: Run all backend tests to verify nothing broke**

Run: `python3 -m pytest tests/test_app.py -v`
Expected: ALL PASS.

- [ ] **Step 9: Commit**

```bash
git add static/index.html static/style.css static/app.js
git commit -m "feat: add conversation mode frontend UI"
```
