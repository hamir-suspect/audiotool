# Audio Router Webapp Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local webapp for controlling PipeWire audio routing — loopback modes, audio file playback through a virtual sink, and volume control.

**Architecture:** Single FastAPI process serving a vanilla HTML/JS/CSS frontend and managing pw-loopback/ffmpeg/paplay subprocesses. SSE pushes real-time state to the browser. The frontend computes playback progress client-side from server-provided `started_at` + `duration`.

**Tech Stack:** Python 3, FastAPI, uvicorn, PipeWire (pw-loopback), ffmpeg/ffprobe, paplay, pactl, pytest, httpx

**Spec:** `docs/superpowers/specs/2026-03-16-audio-router-webapp-design.md`

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `requirements.txt` | Python dependencies |
| Create | `app.py` | FastAPI app, all API endpoints, subprocess management, SSE |
| Create | `static/index.html` | Single page UI with four sections |
| Create | `static/style.css` | Styling |
| Create | `static/app.js` | Frontend logic, SSE handling, API calls |
| Create | `tests/test_app.py` | All backend tests |

---

## Chunk 1: Project Setup + Data APIs

### Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `app.py`
- Create: `static/index.html`

- [ ] **Step 1: Create `requirements.txt`**

```
fastapi
uvicorn
httpx
pytest
```

- [ ] **Step 2: Create minimal `app.py`**

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()


@app.get("/")
async def index():
    html = (Path(__file__).parent / "static" / "index.html").read_text()
    return HTMLResponse(html)


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
```

- [ ] **Step 3: Create `static/index.html` placeholder**

```html
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Audio Router</title></head>
<body><h1>Audio Router</h1></body>
</html>
```

- [ ] **Step 4: Install dependencies and verify server starts**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool && pip install -r requirements.txt
timeout 3 uvicorn app:app --host 0.0.0.0 --port 8000 || true
```

Expected: Server starts without import errors (exits after timeout).

- [ ] **Step 5: Commit**

```bash
git add requirements.txt app.py static/index.html
git commit -m "feat: scaffold FastAPI project with static file serving"
```

---

### Task 2: File Listing API (`/api/files`)

**Files:**
- Modify: `app.py`
- Create: `tests/test_app.py`

- [ ] **Step 1: Write failing tests for `/api/files`**

Create `tests/test_app.py`:

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app import app
    return TestClient(app)


@pytest.fixture
def samples_dir(tmp_path, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "SAMPLES_DIR", tmp_path)
    return tmp_path


def test_list_files_returns_audio_files(samples_dir, client):
    (samples_dir / "song.mp3").touch()
    (samples_dir / "clip.wav").touch()
    (samples_dir / "notes.txt").touch()
    (samples_dir / "video.mp4").touch()

    resp = client.get("/api/files")
    assert resp.status_code == 200
    assert sorted(resp.json()["files"]) == ["clip.wav", "song.mp3", "video.mp4"]


def test_list_files_empty_dir(samples_dir, client):
    resp = client.get("/api/files")
    assert resp.status_code == 200
    assert resp.json()["files"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -v
```

Expected: FAIL — no `SAMPLES_DIR` attribute, no `/api/files` route.

- [ ] **Step 3: Add `/api/files` endpoint to `app.py`**

Add imports and constants at the top (after existing imports), and the endpoint before `app.mount(...)`:

```python
import os

SAMPLES_DIR = Path(os.environ.get("SAMPLES_DIR", "/home/hamir/Documents/samples"))
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".mp4", ".flac", ".m4a"}


@app.get("/api/files")
async def list_files():
    if not SAMPLES_DIR.is_dir():
        return {"files": []}
    files = sorted(
        f.name for f in SAMPLES_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
    )
    return {"files": files}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: add /api/files endpoint with audio file filtering"
```

---

### Task 3: Sinks Listing API (`/api/sinks`)

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write failing test for `/api/sinks`**

Add to `tests/test_app.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch


def test_list_sinks(client):
    pactl_output = (
        "1\talsa_output.pci-0000_00_1f.3.analog-stereo\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
        "2\talsa_output.usb\tUSB Audio\ts32le 2ch 44100Hz\tRUNNING\n"
    )
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(pactl_output.encode(), b""))

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        resp = client.get("/api/sinks")

    assert resp.status_code == 200
    assert resp.json()["sinks"] == [
        "alsa_output.pci-0000_00_1f.3.analog-stereo",
        "alsa_output.usb",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py::test_list_sinks -v
```

Expected: FAIL — no `/api/sinks` route.

- [ ] **Step 3: Add `/api/sinks` endpoint to `app.py`**

Add `import asyncio` at top, and the endpoint before `app.mount(...)`:

```python
import asyncio


@app.get("/api/sinks")
async def list_sinks():
    proc = await asyncio.create_subprocess_exec(
        "pactl", "list", "short", "sinks",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    sinks = []
    for line in stdout.decode().strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            sinks.append(parts[1])
    return {"sinks": sinks}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: add /api/sinks endpoint listing PulseAudio sinks"
```

---

## Chunk 2: State Management + Subprocess APIs

### Task 4: AppState + SSE Status (`/api/status`)

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Add AppState, broadcast_state, and `/api/status` to `app.py`**

Add imports `import json` and `from fastapi import FastAPI, Request` (update existing import), and `from fastapi.responses import HTMLResponse, StreamingResponse` (update existing import).

Add after the constants, before other endpoints:

```python
class AppState:
    def __init__(self):
        self.loopback_running = False
        self.loopback_mode = "virtual-sink"
        self.loopback_process = None
        self.playback_process = None
        self.current_file = None
        self.volume = 300
        self.playback_duration = 0.0
        self.playback_started_at = 0.0
        self.sse_clients: list[asyncio.Queue] = []

    def to_dict(self):
        return {
            "loopback_running": self.loopback_running,
            "loopback_mode": self.loopback_mode,
            "current_file": self.current_file,
            "volume": self.volume,
            "playback_duration": self.playback_duration,
            "playback_started_at": self.playback_started_at,
        }


state = AppState()


async def broadcast_state():
    data = json.dumps(state.to_dict())
    for queue in list(state.sse_clients):
        await queue.put(data)
```

Add the SSE endpoint before `app.mount(...)`:

```python
@app.get("/api/status")
async def status_stream(request: Request):
    queue = asyncio.Queue()
    state.sse_clients.append(queue)

    async def event_generator():
        try:
            yield f"data: {json.dumps(state.to_dict())}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            state.sse_clients.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
```

- [ ] **Step 2: Write SSE test and reset_state fixture**

Add to `tests/test_app.py` (the `reset_state` fixture must be added after AppState exists in app.py — that's why this step comes after Step 1):

```python
import json


@pytest.fixture(autouse=True)
def reset_state():
    from app import state
    state.__init__()
    yield


def test_status_sse_returns_initial_state(client):
    with client.stream("GET", "/api/status") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        for line in resp.iter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                assert data["loopback_running"] is False
                assert data["loopback_mode"] == "virtual-sink"
                assert data["current_file"] is None
                assert data["volume"] == 300
                break
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -v
```

Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: add AppState and SSE /api/status endpoint"
```

---

### Task 5: Loopback Start/Stop (`/api/loopback/start`, `/api/loopback/stop`)

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write failing tests for loopback management**

Add to `tests/test_app.py`:

```python
def test_loopback_start_virtual_sink(client):
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        resp = client.post("/api/loopback/start", json={"mode": "virtual-sink"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    assert resp.json()["mode"] == "virtual-sink"


def test_loopback_start_sink_capture(client):
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        resp = client.post("/api/loopback/start", json={"mode": "sink-capture", "sink": "alsa_output.usb"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    assert resp.json()["mode"] == "sink-capture"


def test_loopback_start_sink_capture_requires_sink(client):
    resp = client.post("/api/loopback/start", json={"mode": "sink-capture"})
    assert "error" in resp.json()


def test_loopback_start_already_running(client):
    from app import state
    state.loopback_running = True

    resp = client.post("/api/loopback/start", json={"mode": "virtual-sink"})
    assert resp.json()["error"] == "Loopback already running"


def test_loopback_stop(client):
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        client.post("/api/loopback/start", json={"mode": "virtual-sink"})
        resp = client.post("/api/loopback/stop")

    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
    mock_proc.terminate.assert_called()


def test_loopback_stop_not_running(client):
    resp = client.post("/api/loopback/stop")
    assert resp.json()["error"] == "Loopback not running"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -k loopback -v
```

Expected: FAIL — no `/api/loopback/start` or `/api/loopback/stop` routes.

- [ ] **Step 3: Add loopback endpoints to `app.py`**

Add `from pydantic import BaseModel`, `import signal`, and `import os` to imports (both needed here for process cleanup in `stop_loopback`).

Add the Pydantic model, helper, and endpoints before `app.mount(...)`:

```python
class LoopbackStartRequest(BaseModel):
    mode: str = "virtual-sink"
    sink: str | None = None


async def _kill_playback():
    """Stop the current playback process and reset playback state."""
    if state.playback_process:
        try:
            os.killpg(os.getpgid(state.playback_process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        await state.playback_process.wait()
        state.playback_process = None
        state.current_file = None
        state.playback_duration = 0.0
        state.playback_started_at = 0.0


@app.post("/api/loopback/start")
async def start_loopback(req: LoopbackStartRequest):
    if state.loopback_running:
        return {"error": "Loopback already running"}

    if req.mode == "virtual-sink":
        cmd = [
            "pw-loopback",
            '--capture-props=media.class=Audio/Sink node.name=VirtualSink node.description="Virtual Sink"',
            '--playback-props=media.class=Audio/Source node.name=VirtualMic node.description="Virtual Mic"',
        ]
    elif req.mode == "sink-capture":
        if not req.sink:
            return {"error": "sink required for sink-capture mode"}
        cmd = [
            "pw-loopback",
            f"--capture-props=node.target={req.sink}",
            '--playback-props=media.class=Audio/Source node.name=VirtualMic node.description="Virtual Mic"',
        ]
    else:
        return {"error": f"Unknown mode: {req.mode}"}

    state.loopback_process = await asyncio.create_subprocess_exec(*cmd)
    state.loopback_running = True
    state.loopback_mode = req.mode
    await broadcast_state()
    return {"status": "started", "mode": req.mode}


@app.post("/api/loopback/stop")
async def stop_loopback():
    if not state.loopback_running:
        return {"error": "Loopback not running"}

    await _kill_playback()

    state.loopback_process.terminate()
    await state.loopback_process.wait()
    state.loopback_process = None
    state.loopback_running = False
    await broadcast_state()
    return {"status": "stopped"}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: add loopback start/stop endpoints with virtual-sink and sink-capture modes"
```

---

### Task 6: Audio Playback (`/api/play`, `/api/stop`)

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write failing tests for playback**

Add to `tests/test_app.py`:

```python
def test_play_file(samples_dir, client):
    (samples_dir / "song.mp3").write_bytes(b"fake audio")
    from app import state
    state.loopback_running = True
    state.loopback_mode = "virtual-sink"

    mock_duration_proc = MagicMock()
    mock_duration_proc.communicate = AsyncMock(return_value=(b"120.5", b""))
    mock_play_proc = MagicMock()
    mock_play_proc.wait = AsyncMock()
    mock_play_proc.pid = 12345

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_duration_proc), \
         patch("asyncio.create_subprocess_shell", new_callable=AsyncMock, return_value=mock_play_proc):
        resp = client.post("/api/play", json={"filename": "song.mp3"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "playing"
    assert resp.json()["filename"] == "song.mp3"


def test_play_requires_virtual_sink_mode(client):
    from app import state
    state.loopback_running = True
    state.loopback_mode = "sink-capture"

    resp = client.post("/api/play", json={"filename": "song.mp3"})
    assert "error" in resp.json()


def test_play_requires_loopback_running(client):
    resp = client.post("/api/play", json={"filename": "song.mp3"})
    assert "error" in resp.json()


def test_stop_playback(client):
    from app import state
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock()
    mock_proc.pid = 12345
    state.playback_process = mock_proc
    state.current_file = "song.mp3"

    with patch("os.killpg"), patch("os.getpgid", return_value=12345):
        resp = client.post("/api/stop")

    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


def test_stop_nothing_playing(client):
    resp = client.post("/api/stop")
    assert resp.json()["error"] == "Nothing playing"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -k "play or stop_playback or stop_nothing" -v
```

Expected: FAIL — no `/api/play` or `/api/stop` routes.

- [ ] **Step 3: Add playback endpoints to `app.py`**

Add `import shlex` and `import time` to imports.

Add Pydantic model and endpoints before `app.mount(...)`. Uses the `_kill_playback()` helper from Task 5 to avoid duplication:

```python
class PlayRequest(BaseModel):
    filename: str


@app.post("/api/play")
async def play_file(req: PlayRequest):
    if not state.loopback_running or state.loopback_mode != "virtual-sink":
        return {"error": "Loopback must be running in virtual-sink mode"}

    filepath = (SAMPLES_DIR / req.filename).resolve()
    if not filepath.is_relative_to(SAMPLES_DIR.resolve()):
        return {"error": "Invalid filename"}
    if not filepath.is_file():
        return {"error": "File not found"}

    # Stop current playback if any
    await _kill_playback()

    # Get duration via ffprobe
    duration_proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(filepath),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await duration_proc.communicate()
    try:
        state.playback_duration = float(stdout.decode().strip())
    except ValueError:
        state.playback_duration = 0.0

    # Start ffmpeg | paplay pipeline
    cmd = f"ffmpeg -i {shlex.quote(str(filepath))} -f wav -ac 2 -ar 48000 - 2>/dev/null | paplay --device=VirtualSink"
    state.playback_process = await asyncio.create_subprocess_shell(
        cmd, start_new_session=True,
    )
    state.current_file = req.filename
    state.playback_started_at = time.time()
    await broadcast_state()

    asyncio.create_task(_monitor_playback(state.playback_process))
    return {"status": "playing", "filename": req.filename}


async def _monitor_playback(proc):
    await proc.wait()
    if state.playback_process is proc:
        state.playback_process = None
        state.current_file = None
        state.playback_duration = 0.0
        state.playback_started_at = 0.0
        await broadcast_state()


@app.post("/api/stop")
async def stop_playback():
    if not state.playback_process:
        return {"error": "Nothing playing"}

    await _kill_playback()
    await broadcast_state()
    return {"status": "stopped"}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -v
```

Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: add audio playback endpoints with ffmpeg/paplay pipeline"
```

---

### Task 7: Volume Control (`/api/volume`)

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write failing test for volume**

Add to `tests/test_app.py`:

```python
def test_set_volume(client):
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        resp = client.post("/api/volume", json={"percent": 150})

    assert resp.status_code == 200
    assert resp.json()["percent"] == 150
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py::test_set_volume -v
```

Expected: FAIL — no `/api/volume` route.

- [ ] **Step 3: Add volume endpoint to `app.py`**

Add before `app.mount(...)`:

```python
class VolumeRequest(BaseModel):
    percent: int


@app.post("/api/volume")
async def set_volume(req: VolumeRequest):
    proc = await asyncio.create_subprocess_exec(
        "pactl", "set-source-volume", "VirtualMic", f"{req.percent}%"
    )
    await proc.wait()
    state.volume = req.percent
    await broadcast_state()
    return {"status": "ok", "percent": req.percent}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -v
```

Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: add /api/volume endpoint for virtual mic volume control"
```

---

## Chunk 3: Frontend

> **Spec deviations (intentional):** The spec mentions "pause/stop controls" and "seek/progress bar" in the Now Playing section. Pause and seek are omitted because the `ffmpeg | paplay` shell pipeline cannot be paused (no STDIN control) or seeked (would require restarting the pipeline from a new offset). The progress bar is display-only. Only stop is implemented.

### Task 8: Frontend — HTML, CSS, JavaScript

**Files:**
- Overwrite: `static/index.html`
- Create: `static/style.css`
- Create: `static/app.js`

- [ ] **Step 1: Write `static/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Audio Router</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <h1>Audio Router</h1>

    <section id="loopback-control">
        <h2>Loopback Control</h2>
        <div class="control-row">
            <label for="mode-select">Mode:</label>
            <select id="mode-select">
                <option value="virtual-sink">Virtual Sink</option>
                <option value="sink-capture">Sink Capture</option>
            </select>
        </div>
        <div id="sink-group" class="control-row" style="display:none">
            <label for="sink-select">Sink:</label>
            <select id="sink-select"></select>
        </div>
        <div class="control-row">
            <button id="btn-start" onclick="startLoopback()">Start</button>
            <button id="btn-stop" onclick="stopLoopback()" disabled>Stop</button>
            <span id="loopback-status" class="status-off">Stopped</span>
        </div>
    </section>

    <section id="volume-control">
        <h2>Volume</h2>
        <div class="control-row">
            <input type="range" id="volume-slider" min="0" max="500" value="300">
            <span id="volume-value">300%</span>
        </div>
    </section>

    <section id="audio-files">
        <h2>Audio Files</h2>
        <ul id="file-list"></ul>
    </section>

    <section id="now-playing" style="display:none">
        <h2>Now Playing</h2>
        <p id="now-playing-file"></p>
        <div class="progress-container">
            <div id="progress-bar" class="progress-bar"></div>
        </div>
        <span id="progress-time">0:00 / 0:00</span>
        <button onclick="stopPlayback()">Stop</button>
    </section>

    <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `static/style.css`**

```css
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: system-ui, -apple-system, sans-serif;
    max-width: 600px;
    margin: 0 auto;
    padding: 1rem;
    background: #1a1a2e;
    color: #eee;
}

h1 { margin-bottom: 1.5rem; }
h2 { margin-bottom: 0.75rem; font-size: 1.1rem; color: #aaa; }

section {
    background: #16213e;
    border-radius: 8px;
    padding: 1rem;
    margin-bottom: 1rem;
}

.control-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.5rem;
}

select, button, input[type="range"] {
    font-size: 0.9rem;
}

select {
    padding: 0.4rem;
    border-radius: 4px;
    background: #0f3460;
    color: #eee;
    border: 1px solid #333;
}

button {
    padding: 0.4rem 1rem;
    border-radius: 4px;
    border: none;
    background: #e94560;
    color: white;
    cursor: pointer;
}

button:hover { background: #c73a52; }
button:disabled { background: #555; cursor: not-allowed; }

.status-on { color: #4ecca3; font-weight: bold; }
.status-off { color: #888; }

input[type="range"] { flex: 1; }

#file-list {
    list-style: none;
    max-height: 300px;
    overflow-y: auto;
}

#file-list li {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.4rem 0;
    border-bottom: 1px solid #1a1a2e;
}

#file-list li span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
    margin-right: 0.5rem;
}

.progress-container {
    background: #0f3460;
    border-radius: 4px;
    height: 8px;
    margin: 0.5rem 0;
    overflow: hidden;
}

.progress-bar {
    background: #e94560;
    height: 100%;
    width: 0%;
    transition: width 0.5s linear;
}

#progress-time {
    font-size: 0.8rem;
    color: #888;
}
```

- [ ] **Step 3: Write `static/app.js`**

```javascript
const state = {
    loopback_running: false,
    loopback_mode: "virtual-sink",
    current_file: null,
    volume: 300,
    playback_duration: 0,
    playback_started_at: 0,
};

// SSE connection
const evtSource = new EventSource("/api/status");
evtSource.onmessage = (event) => {
    Object.assign(state, JSON.parse(event.data));
    render();
};

// --- API functions ---

async function startLoopback() {
    const mode = document.getElementById("mode-select").value;
    const body = { mode };
    if (mode === "sink-capture") {
        body.sink = document.getElementById("sink-select").value;
    }
    await fetch("/api/loopback/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
}

async function stopLoopback() {
    await fetch("/api/loopback/stop", { method: "POST" });
}

async function playFile(filename) {
    await fetch("/api/play", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename }),
    });
}

async function stopPlayback() {
    await fetch("/api/stop", { method: "POST" });
}

async function setVolume(percent) {
    await fetch("/api/volume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ percent: parseInt(percent) }),
    });
}

async function loadFiles() {
    const resp = await fetch("/api/files");
    const data = await resp.json();
    const list = document.getElementById("file-list");
    list.innerHTML = "";
    data.files.forEach((file) => {
        const li = document.createElement("li");
        const span = document.createElement("span");
        span.textContent = file;
        const btn = document.createElement("button");
        btn.className = "play-btn";
        btn.textContent = "Play";
        btn.onclick = () => playFile(file);
        li.appendChild(span);
        li.appendChild(btn);
        list.appendChild(li);
    });
}

async function loadSinks() {
    const resp = await fetch("/api/sinks");
    const data = await resp.json();
    const select = document.getElementById("sink-select");
    select.innerHTML = "";
    data.sinks.forEach((sink) => {
        const option = document.createElement("option");
        option.value = sink;
        option.textContent = sink;
        select.appendChild(option);
    });
}

// --- Rendering ---

function formatTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
}

function render() {
    // Loopback status
    const statusEl = document.getElementById("loopback-status");
    statusEl.textContent = state.loopback_running
        ? `Running (${state.loopback_mode})`
        : "Stopped";
    statusEl.className = state.loopback_running ? "status-on" : "status-off";

    // Start/stop buttons
    document.getElementById("btn-start").disabled = state.loopback_running;
    document.getElementById("btn-stop").disabled = !state.loopback_running;

    // Volume
    document.getElementById("volume-slider").value = state.volume;
    document.getElementById("volume-value").textContent = `${state.volume}%`;

    // Now playing
    const nowPlaying = document.getElementById("now-playing");
    if (state.current_file) {
        nowPlaying.style.display = "block";
        document.getElementById("now-playing-file").textContent =
            state.current_file;
    } else {
        nowPlaying.style.display = "none";
    }

    // Play button state
    document.querySelectorAll(".play-btn").forEach((btn) => {
        btn.disabled =
            !state.loopback_running ||
            state.loopback_mode !== "virtual-sink";
    });
}

// --- Event handlers ---

document.getElementById("mode-select").addEventListener("change", function () {
    const isSinkCapture = this.value === "sink-capture";
    document.getElementById("sink-group").style.display = isSinkCapture
        ? "flex"
        : "none";
    if (isSinkCapture) loadSinks();
});

document
    .getElementById("volume-slider")
    .addEventListener("input", function () {
        document.getElementById(
            "volume-value"
        ).textContent = `${this.value}%`;
    });

document
    .getElementById("volume-slider")
    .addEventListener("change", function () {
        setVolume(this.value);
    });

// Progress bar update
setInterval(() => {
    if (state.current_file && state.playback_duration > 0) {
        const elapsed = Date.now() / 1000 - state.playback_started_at;
        const progress = Math.min(
            (elapsed / state.playback_duration) * 100,
            100
        );
        document.getElementById("progress-bar").style.width = `${progress}%`;
        document.getElementById("progress-time").textContent = `${formatTime(
            elapsed
        )} / ${formatTime(state.playback_duration)}`;
    }
}, 500);

// Initial load
loadFiles();
```

- [ ] **Step 4: Smoke test the server**

Start the server in the background, run a quick curl check, then stop it:

```bash
cd /home/hamir/Documents/dsoignoo/audiotool && uvicorn app:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!
sleep 2
curl -s http://localhost:8000 | grep -q "Audio Router" && echo "HTML OK" || echo "HTML FAIL"
curl -s http://localhost:8000/api/files | python3 -c "import sys,json; d=json.load(sys.stdin); print('Files OK' if 'files' in d else 'Files FAIL')"
curl -s http://localhost:8000/static/app.js | grep -q "EventSource" && echo "JS OK" || echo "JS FAIL"
kill $SERVER_PID
```

Expected: `HTML OK`, `Files OK`, `JS OK`.

- [ ] **Step 5: Run all tests to confirm nothing broke**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -v
```

Expected: 16 passed.

- [ ] **Step 6: Commit**

```bash
git add static/index.html static/style.css static/app.js
git commit -m "feat: add frontend UI with SSE, loopback controls, file browser, and playback"
```
