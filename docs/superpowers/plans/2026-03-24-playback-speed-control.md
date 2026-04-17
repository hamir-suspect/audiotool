# Playback Speed Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add playback speed control (0.5x–2.0x) with preset buttons, changeable mid-playback via pipeline restart with seek.

**Architecture:** The ffmpeg|paplay pipeline is killed and restarted with `-ss <position>` and `-filter:a "atempo=<speed>"` when speed changes. Position is tracked as `playback_position + (wall_elapsed * speed)`. Frontend gets speed state via SSE and renders preset buttons.

**Tech Stack:** Python/FastAPI backend, vanilla JS frontend, ffmpeg atempo filter, SSE state broadcasting.

**Spec:** `docs/superpowers/specs/2026-03-23-playback-speed-control-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app.py` | Modify | Add speed state, `_kill_playback(preserve_metadata)`, `_start_playback_pipeline()` helper, `POST /api/speed`, update `play_file` and `_monitor_playback` |
| `static/index.html` | Modify | Add speed button row to now-playing section |
| `static/app.js` | Modify | Add `setSpeed()` with cooldown, update progress bar calc, update `render()` for active button |
| `static/style.css` | Modify | Add `.speed-btn` and `.speed-btn.active` styles |
| `tests/test_app.py` | Modify | Add speed tests, update SSE initial state test |

---

### Task 1: Add speed fields to AppState

**Files:**
- Modify: `app.py:20-40` (AppState class)
- Test: `tests/test_app.py`

- [ ] **Step 1: Update existing SSE test to assert new fields**

In `tests/test_app.py`, add two assertions to the end of `test_status_sse_returns_initial_state` (after line 96):

```python
    assert data["playback_speed"] == 1.0
    assert data["playback_position"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py::test_status_sse_returns_initial_state -v`
Expected: FAIL — `KeyError: 'playback_speed'`

- [ ] **Step 3: Add fields to AppState and to_dict**

In `app.py`, add three fields to `AppState.__init__()` after line 29:

```python
        self.playback_speed = 1.0
        self.playback_position = 0.0
        self.current_filepath = None
```

Add to `to_dict()` return dict after `"playback_started_at"`:

```python
            "playback_speed": self.playback_speed,
            "playback_position": self.playback_position,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py::test_status_sse_returns_initial_state -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check no regressions**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool
git add app.py tests/test_app.py
git commit -m "feat: add playback_speed and playback_position to AppState"
```

---

### Task 2: Refactor _kill_playback with preserve_metadata

**Files:**
- Modify: `app.py:125-136` (`_kill_playback` function)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write failing test — preserve_metadata=True keeps file metadata**

Add to `tests/test_app.py`:

```python
@pytest.mark.anyio
async def test_kill_playback_preserve_metadata():
    """preserve_metadata=True keeps current_file, duration, speed, filepath."""
    from app import state, _kill_playback

    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock()
    mock_proc.pid = 12345

    state.playback_process = mock_proc
    state.current_file = "song.mp3"
    state.playback_duration = 120.5
    state.playback_started_at = 1000.0
    state.playback_position = 30.0
    state.playback_speed = 1.5
    state.current_filepath = "/path/to/song.mp3"

    with patch("os.killpg"), patch("os.getpgid", return_value=12345):
        await _kill_playback(preserve_metadata=True)

    assert state.playback_process is None
    assert state.current_file == "song.mp3"
    assert state.playback_duration == 120.5
    assert state.playback_speed == 1.5
    assert state.current_filepath == "/path/to/song.mp3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py::test_kill_playback_preserve_metadata -v`
Expected: FAIL — `TypeError: _kill_playback() got an unexpected keyword argument 'preserve_metadata'`

- [ ] **Step 3: Implement preserve_metadata parameter**

Replace `_kill_playback()` in `app.py` (lines 125-136) with:

```python
async def _kill_playback(preserve_metadata=False):
    """Stop the current playback process and reset playback state."""
    if state.playback_process:
        try:
            os.killpg(os.getpgid(state.playback_process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        await state.playback_process.wait()
        state.playback_process = None
        if not preserve_metadata:
            state.current_file = None
            state.playback_duration = 0.0
            state.playback_started_at = 0.0
            state.playback_speed = 1.0
            state.playback_position = 0.0
            state.current_filepath = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py::test_kill_playback_preserve_metadata -v`
Expected: PASS

- [ ] **Step 5: Run full suite — existing tests still pass**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -v`
Expected: All tests PASS (existing `test_stop_playback` uses default `preserve_metadata=False`)

- [ ] **Step 6: Commit**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool
git add app.py tests/test_app.py
git commit -m "refactor: add preserve_metadata param to _kill_playback"
```

---

### Task 3: Extract _start_playback_pipeline helper and update play_file

**Files:**
- Modify: `app.py:187-223` (`play_file` function, new helper)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write failing test — play resets speed to 1.0**

Add to `tests/test_app.py`:

```python
def test_play_resets_speed(samples_dir, client):
    """Playing a new file resets playback_speed to 1.0."""
    from app import state
    state.loopback_running = True
    state.loopback_mode = "virtual-sink"
    state.playback_speed = 1.5  # was playing at 1.5x

    (samples_dir / "song.mp3").write_bytes(b"fake audio")

    mock_duration_proc = MagicMock()
    mock_duration_proc.communicate = AsyncMock(return_value=(b"120.5", b""))
    mock_play_proc = MagicMock()
    mock_play_proc.wait = AsyncMock()
    mock_play_proc.pid = 12345

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_duration_proc), \
         patch("asyncio.create_subprocess_shell", new_callable=AsyncMock, return_value=mock_play_proc):
        resp = client.post("/api/play", json={"filename": "song.mp3"})

    assert resp.status_code == 200
    assert state.playback_speed == 1.0
    assert state.playback_position == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py::test_play_resets_speed -v`
Expected: FAIL — `assert 1.5 == 1.0`

- [ ] **Step 3: Extract helper and update play_file**

Add the `ALLOWED_SPEEDS` constant and `_start_playback_pipeline` helper to `app.py`, right after `_kill_playback()`:

```python
ALLOWED_SPEEDS = {0.5, 0.75, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0}


async def _start_playback_pipeline(filepath, position, speed):
    """Launch the ffmpeg | paplay pipeline with seek and speed."""
    ss_arg = f"-ss {position}" if position > 0 else ""
    cmd = (
        f"ffmpeg {ss_arg} -i {shlex.quote(str(filepath))} "
        f"-filter:a atempo={speed} -f wav -ac 2 -ar 48000 - 2>/dev/null "
        f"| paplay --device=VirtualSink"
    )
    state.playback_process = await asyncio.create_subprocess_shell(
        cmd, start_new_session=True,
    )
    state.playback_started_at = time.time()
    asyncio.create_task(_monitor_playback(state.playback_process))
```

Replace the `play_file` endpoint body (after the filepath validation and ffprobe duration block, starting at the `# Start ffmpeg | paplay pipeline` comment) with:

```python
    # Reset speed state for new playback
    state.playback_speed = 1.0
    state.playback_position = 0.0
    state.current_filepath = str(filepath)

    # Start ffmpeg | paplay pipeline
    await _start_playback_pipeline(filepath, 0, state.playback_speed)
    state.current_file = req.filename
    await broadcast_state()

    return {"status": "playing", "filename": req.filename}
```

This removes the old inline ffmpeg command, the manual `playback_started_at` assignment, and the manual `create_task` call — all now handled by the helper.

- [ ] **Step 4: Run the new test**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py::test_play_resets_speed -v`
Expected: PASS

- [ ] **Step 5: Run full suite — no regressions**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool
git add app.py tests/test_app.py
git commit -m "refactor: extract _start_playback_pipeline helper, play resets speed"
```

---

### Task 4: Add POST /api/speed endpoint

**Files:**
- Modify: `app.py` (new endpoint after `stop_playback`)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write failing tests for speed endpoint**

Add to `tests/test_app.py`:

```python
def test_set_speed_no_playback(client):
    """Setting speed with nothing playing just stores it."""
    resp = client.post("/api/speed", json={"speed": 1.5})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["speed"] == 1.5

    from app import state
    assert state.playback_speed == 1.5


def test_set_speed_invalid(client):
    """Reject speed values not in ALLOWED_SPEEDS."""
    resp = client.post("/api/speed", json={"speed": 3.0})
    assert "error" in resp.json()

    resp = client.post("/api/speed", json={"speed": 0.0})
    assert "error" in resp.json()


def test_set_speed_during_playback(client):
    """Speed change mid-playback kills and restarts pipeline with seek."""
    from app import state

    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock()
    mock_proc.pid = 12345
    state.playback_process = mock_proc
    state.current_file = "song.mp3"
    state.current_filepath = "/tmp/song.mp3"
    state.playback_duration = 120.0
    state.playback_speed = 1.0
    state.playback_position = 0.0
    state.playback_started_at = 1000.0  # started at t=1000

    mock_new_proc = MagicMock()
    mock_new_proc.wait = AsyncMock()
    mock_new_proc.pid = 99999

    with patch("os.killpg"), \
         patch("os.getpgid", return_value=12345), \
         patch("app.time.time", return_value=1010.0), \
         patch("asyncio.create_subprocess_shell", new_callable=AsyncMock, return_value=mock_new_proc) as mock_shell:
        resp = client.post("/api/speed", json={"speed": 1.5})

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        # Position should be: 0.0 + (1010 - 1000) * 1.0 = 10.0 seconds into source
        assert state.playback_position == 10.0
        assert state.playback_speed == 1.5
        assert state.current_file == "song.mp3"

        # Verify ffmpeg was restarted with atempo and -ss
        call_args = mock_shell.call_args[0][0]
        assert "atempo=1.5" in call_args
        assert "-ss 10.0" in call_args


def test_set_speed_near_end_stops(client):
    """Speed change when position >= duration stops instead of restarting."""
    from app import state

    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock()
    mock_proc.pid = 12345
    state.playback_process = mock_proc
    state.current_file = "song.mp3"
    state.current_filepath = "/tmp/song.mp3"
    state.playback_duration = 60.0
    state.playback_speed = 2.0
    state.playback_position = 50.0
    state.playback_started_at = 1000.0

    with patch("os.killpg"), \
         patch("os.getpgid", return_value=12345), \
         patch("app.time.time", return_value=1006.0):  # 6s wall = 12s source. 50+12=62 >= 60
        resp = client.post("/api/speed", json={"speed": 1.0})

    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
    assert state.current_file is None
    assert state.playback_speed == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py::test_set_speed_no_playback tests/test_app.py::test_set_speed_invalid tests/test_app.py::test_set_speed_during_playback tests/test_app.py::test_set_speed_near_end_stops -v`
Expected: FAIL — 404 or no route for `/api/speed`

- [ ] **Step 3: Implement the speed endpoint**

Add to `app.py` after the `stop_playback` endpoint (after line 243):

```python
class SpeedRequest(BaseModel):
    speed: float


@app.post("/api/speed")
async def set_speed(req: SpeedRequest):
    if req.speed not in ALLOWED_SPEEDS:
        return {"error": f"Invalid speed. Allowed: {sorted(ALLOWED_SPEEDS)}"}

    old_speed = state.playback_speed
    state.playback_speed = req.speed

    if not state.playback_process:
        await broadcast_state()
        return {"status": "ok", "speed": req.speed}

    # Calculate current position in source audio
    pos = state.playback_position + (time.time() - state.playback_started_at) * old_speed

    # If near end, just stop
    if pos >= state.playback_duration:
        await _kill_playback()
        await broadcast_state()
        return {"status": "stopped"}

    # Kill pipeline but keep file metadata
    await _kill_playback(preserve_metadata=True)

    # Restart at new speed from calculated position
    state.playback_position = pos
    await _start_playback_pipeline(state.current_filepath, pos, req.speed)
    await broadcast_state()
    return {"status": "ok", "speed": req.speed}
```

- [ ] **Step 4: Run the speed tests**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py::test_set_speed_no_playback tests/test_app.py::test_set_speed_invalid tests/test_app.py::test_set_speed_during_playback tests/test_app.py::test_set_speed_near_end_stops -v`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool
git add app.py tests/test_app.py
git commit -m "feat: add POST /api/speed endpoint with mid-playback restart"
```

---

### Task 5: Update _monitor_playback to reset speed fields

**Files:**
- Modify: `app.py:226-233` (`_monitor_playback`)
- Test: `tests/test_app.py`

- [ ] **Step 1: Update _monitor_playback**

In `app.py`, update the `_monitor_playback` function to also reset the new fields on natural completion:

```python
async def _monitor_playback(proc):
    await proc.wait()
    if state.playback_process is proc:
        state.playback_process = None
        state.current_file = None
        state.playback_duration = 0.0
        state.playback_started_at = 0.0
        state.playback_speed = 1.0
        state.playback_position = 0.0
        state.current_filepath = None
        await broadcast_state()
```

- [ ] **Step 2: Run full suite — no regressions**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool
git add app.py
git commit -m "fix: reset speed fields on natural playback completion"
```

---

### Task 6: Frontend — speed buttons, CSS, and JS

**Files:**
- Modify: `static/index.html:45-53` (now-playing section)
- Modify: `static/style.css` (add speed-btn styles)
- Modify: `static/app.js` (add setSpeed, update render, fix progress bar)

- [ ] **Step 1: Add speed buttons to HTML**

In `static/index.html`, add the speed control row between the `<span id="progress-time">` line and the stop button (between lines 51 and 52):

```html
        <div id="speed-controls" class="control-row">
            <button class="speed-btn" onclick="setSpeed(0.5)">0.5x</button>
            <button class="speed-btn" onclick="setSpeed(0.75)">0.75x</button>
            <button class="speed-btn active" onclick="setSpeed(1.0)">1.0x</button>
            <button class="speed-btn" onclick="setSpeed(1.1)">1.1x</button>
            <button class="speed-btn" onclick="setSpeed(1.25)">1.25x</button>
            <button class="speed-btn" onclick="setSpeed(1.5)">1.5x</button>
            <button class="speed-btn" onclick="setSpeed(1.75)">1.75x</button>
            <button class="speed-btn" onclick="setSpeed(2.0)">2.0x</button>
        </div>
```

- [ ] **Step 2: Add CSS for speed buttons**

Append to `static/style.css`:

```css
.speed-btn {
    padding: 0.3rem 0.5rem;
    font-size: 0.8rem;
    background: #0f3460;
}

.speed-btn.active {
    background: #e94560;
}

.speed-btn:hover:not(:disabled) {
    background: #c73a52;
}
```

- [ ] **Step 3: Add setSpeed function with cooldown to JS**

In `static/app.js`, add to the state object (after `playback_started_at: 0`):

```javascript
    playback_speed: 1.0,
    playback_position: 0,
```

Add the `setSpeed` function after `setVolume`:

```javascript
let speedCooldown = false;

async function setSpeed(speed) {
    if (speedCooldown) return;
    speedCooldown = true;
    setTimeout(() => { speedCooldown = false; }, 300);

    await fetch("/api/speed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ speed }),
    });
}
```

- [ ] **Step 4: Update render() to highlight active speed button**

Add to the `render()` function in `static/app.js`, inside the `if (state.current_file)` block:

```javascript
        // Speed button highlight
        document.querySelectorAll(".speed-btn").forEach((btn) => {
            const btnSpeed = parseFloat(btn.textContent);
            btn.classList.toggle("active", btnSpeed === state.playback_speed);
        });
```

- [ ] **Step 5: Fix progress bar to account for speed**

In `static/app.js`, replace the `setInterval` progress bar block (lines 155-167) with:

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
}, 500);
```

- [ ] **Step 6: Verify in browser (manual)**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && make` (starts uvicorn)
Open: `http://localhost:8000`
Verify: speed buttons appear, active button highlights, clicking changes speed.

- [ ] **Step 7: Run backend tests — no regressions**

Run: `cd /home/hamir/Documents/dsoignoo/audiotool && python -m pytest tests/test_app.py -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool
git add static/index.html static/app.js static/style.css
git commit -m "feat: add frontend speed control buttons with progress bar fix"
```
