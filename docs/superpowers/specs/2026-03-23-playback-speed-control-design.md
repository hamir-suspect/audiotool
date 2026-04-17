# Playback Speed Control Design

**Date:** 2026-03-23
**Status:** Draft

## Overview

Add playback speed control to the audio router, allowing users to change speed (0.5x–2.0x) via preset buttons. Speed is changeable mid-playback by restarting the ffmpeg pipeline with a seek offset and `atempo` filter.

## Backend Changes

### AppState

Add three fields:

- `playback_speed: float = 1.0` — current playback speed multiplier
- `playback_position: float = 0.0` — position (in seconds) in the original file at the moment the current pipeline segment started
- `current_filepath: str | None = None` — full path to the current file (needed for pipeline restart)

Include `playback_speed` and `playback_position` in `to_dict()` for SSE broadcasts.

### New Endpoint: `POST /api/speed`

Request body: `{"speed": float}`

Validation: speed must be one of `[0.5, 0.75, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0]`.

Behavior:
1. Validate speed value
2. Update `state.playback_speed`
3. If nothing is playing, just store the speed and broadcast — done
4. If playing:
   a. Calculate current position in source: `pos = state.playback_position + (time.time() - state.playback_started_at) * state.playback_speed`
   b. Clamp: if `pos >= state.playback_duration`, stop playback instead of restarting (edge case near end of file)
   c. Kill current pipeline via `_kill_playback(preserve_metadata=True)`
   d. Restart pipeline via `_start_playback_pipeline()`. If the restart fails (process exits immediately), reset to stopped state and broadcast
   e. Update `state.playback_position = pos`, `state.playback_started_at = time.time()`
   f. Broadcast state

**Race condition guard:** Disable speed buttons in the frontend for 300ms after a click to prevent rapid successive pipeline restarts.

### Modified: `POST /api/play`

- Reset `playback_speed` to `1.0` and `playback_position` to `0.0`
- Store `current_filepath` for use during speed-change restarts
- Build ffmpeg command with `atempo` filter if speed != 1.0 (for consistency, always include the filter)

### Modified: ffmpeg Command

Before:
```
ffmpeg -i <file> -f wav -ac 2 -ar 48000 - | paplay --device=VirtualSink
```

After:
```
ffmpeg -ss <position> -i <file> -filter:a "atempo=<speed>" -f wav -ac 2 -ar 48000 - | paplay --device=VirtualSink
```

### Modified: `_kill_playback()`

Add a parameter `preserve_metadata: bool = False`.

When `preserve_metadata=True` (used during speed changes):
- Kill the subprocess and wait for it
- Set `state.playback_process = None`
- **Preserve:** `current_file`, `playback_duration`, `current_filepath`, `playback_speed`
- **Do NOT preserve:** `playback_started_at`, `playback_position` — these are recalculated by the caller after restart

When `preserve_metadata=False` (default, used for actual stop):
- Kill the subprocess and wait for it
- Reset **all** playback state: `playback_process`, `current_file`, `playback_duration`, `playback_started_at`, `playback_position`, `playback_speed`, `current_filepath`

### Modified: `_monitor_playback()`

On natural completion, also reset `playback_speed` to `1.0`, `playback_position` to `0.0`, and `current_filepath` to `None`.

### Helper: `_start_playback_pipeline(filepath, position, speed)`

Extract the ffmpeg pipeline launch into a reusable helper since both `play_file` and `set_speed` need it. This helper:
1. Builds the ffmpeg command with `-ss` and `atempo`
2. Launches the subprocess
3. Sets `state.playback_started_at`
4. Creates the monitor task

## Frontend Changes

### State

Add to local state object:
- `playback_speed: 1.0`
- `playback_position: 0`

These are populated from SSE broadcasts.

### UI: Speed Buttons

Add a row of preset buttons in the "Now Playing" section, between the progress bar/time and the stop button:

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

### API Function

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

### Render Updates

- Highlight the active speed button (add `.active` class matching `state.playback_speed`)
- Fix progress bar calculation to account for speed:
  ```
  elapsed_in_source = state.playback_position + (Date.now()/1000 - state.playback_started_at) * state.playback_speed
  progress = (elapsed_in_source / state.playback_duration) * 100
  ```
- Update time display to show position in original file (not wall-clock elapsed)

### CSS

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

## Reset Behavior

- `POST /api/play`: resets speed to 1.0, position to 0.0
- `POST /api/stop`: resets speed to 1.0, position to 0.0
- Natural playback end: resets speed to 1.0, position to 0.0
- Loopback stop: kills playback, which resets everything

## Testing

New tests:
- `test_set_speed_no_playback` — stores speed, returns ok
- `test_set_speed_invalid` — rejects invalid speed values
- `test_set_speed_during_playback` — verifies pipeline restart with correct seek and atempo; mock `time.time()` to assert exact seek position
- `test_set_speed_near_end_stops` — when calculated position >= duration, stops instead of restarting
- `test_speed_in_state_broadcast` — new fields appear in SSE state
- `test_play_resets_speed` — speed resets to 1.0 on new play

Existing tests updated:
- `test_status_sse_returns_initial_state` — assert `playback_speed` and `playback_position` in initial state
