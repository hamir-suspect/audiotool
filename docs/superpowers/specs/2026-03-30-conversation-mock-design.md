# Conversation Mock Mode — Design Spec

## Overview

Add a "conversation mode" to the audio router webapp that creates two virtual microphones and plays a scripted sequence of audio files through them in alternating turns, simulating a two-person conversation. This is intended for use with video call apps (Google Meet, Zoom) where each virtual mic is assigned to a different participant via separate browser tabs.

The existing single-mic playback mode remains fully functional alongside this feature. The two modes are mutually exclusive — starting one stops the other.

## Script Format

Conversation scripts are JSON files stored in `SAMPLES_DIR/conversations/`. Format:

```json
{
  "gap": 1.0,
  "turns": [
    {"speaker": 1, "file": "hello.mp3"},
    {"speaker": 2, "file": "hi-there.mp3"},
    {"speaker": 1, "file": "how-are-you.mp3"},
    {"speaker": 2, "file": "good-thanks.mp3"}
  ]
}
```

- `gap` — seconds of silence between turns. Defaults to `1.0` if omitted.
- `speaker` — `1` or `2`, mapping to VirtualMic1 or VirtualMic2.
- `file` — audio filename resolved relative to `SAMPLES_DIR`.

## Backend State

New state structure alongside existing `AppState`:

```python
class ConversationState:
    running: bool                    # conversation mode active
    script_path: str | None          # loaded script file
    turns: list[dict]                # the turn sequence
    current_turn: int                # index into turns (-1 when idle)
    gap: float                       # seconds between turns
    loopback1_process: subprocess    # pw-loopback for VirtualSink1/VirtualMic1
    loopback2_process: subprocess    # pw-loopback for VirtualSink2/VirtualMic2
    playback_process: subprocess     # current turn's ffmpeg|paplay
    playback_duration: float         # current turn's file duration
    playback_started_at: float       # unix timestamp for progress tracking
```

## Loopback Management

When a conversation starts, two `pw-loopback` processes are created:

```bash
pw-loopback --capture-props='media.class=Audio/Sink node.name=VirtualSink1' \
            --playback-props='media.class=Audio/Source node.name=VirtualMic1'

pw-loopback --capture-props='media.class=Audio/Sink node.name=VirtualSink2' \
            --playback-props='media.class=Audio/Source node.name=VirtualMic2'
```

These are torn down when the conversation stops or completes.

## Turn Execution

The conversation runs as a background `asyncio` task:

```
START -> play_turn(0) -> wait_for_completion -> gap(1s) -> play_turn(1) -> ... -> DONE
```

Each turn:
1. Look up `speaker` (1 or 2) to determine target sink (`VirtualSink1` or `VirtualSink2`).
2. Get file duration via `ffprobe`.
3. Start `ffmpeg -i <file> -f wav -ac 2 -ar 48000 - 2>/dev/null | paplay --device=VirtualSinkN`.
4. Update conversation state (`current_turn`, `playback_duration`, `playback_started_at`).
5. Broadcast state via SSE.
6. Wait for the playback process to finish.
7. If more turns remain: `asyncio.sleep(gap)`, then next turn.
8. When all turns complete: broadcast "conversation finished" state, tear down loopbacks, reset state.

**Cancellation:** `/api/conversation/stop` cancels the background task, kills the playback process, and tears down both loopbacks.

**Error handling:** If a file fails to play (ffmpeg error, missing file), the conversation stops and the error is reported via SSE. No attempt to skip to the next turn.

**Speed/volume:** Not supported in conversation mode. These controls only apply to the existing single-mic mode.

## Mutual Exclusion

- Starting a conversation while single-mic loopback is running stops the single-mic loopback first.
- Starting single-mic loopback while a conversation is running stops the conversation first.

## API Endpoints

| Method | Path | Body | Purpose |
|--------|------|------|---------|
| GET | `/api/conversations` | — | List `.json` script files from `SAMPLES_DIR/conversations/` |
| POST | `/api/conversation/start` | `{"script": "chat.json"}` | Validate script, start loopbacks, begin turn playback |
| POST | `/api/conversation/stop` | — | Cancel conversation, kill processes, tear down loopbacks |

### Validation on `/api/conversation/start`

- Script file must exist in `SAMPLES_DIR/conversations/`.
- JSON must parse successfully.
- Must contain a `turns` array with at least one entry.
- Each turn must have `speaker` (1 or 2) and `file` (string).
- Each referenced audio file must exist in `SAMPLES_DIR`.

## SSE State

The `/api/status` SSE stream is extended with conversation fields alongside existing fields:

```json
{
  "conversation_running": false,
  "conversation_script": null,
  "conversation_turns": [],
  "conversation_current_turn": -1,
  "conversation_gap": 1.0,
  "conversation_playback_duration": 0,
  "conversation_playback_started_at": 0
}
```

## Frontend

A new "Conversation Mode" section in the UI, separate from existing controls:

- **Script selector** — dropdown listing scripts from `/api/conversations`, with a "Start Conversation" button.
- **Now Playing (Conversation)** — shown when a conversation is running:
  - Current turn number / total turns (e.g., "Turn 3 of 8").
  - Current speaker indicator (Speaker 1 / Speaker 2).
  - Current file being played.
  - Progress bar for the current turn.
  - "Stop Conversation" button.

The existing loopback controls, file browser, and playback section are hidden when a conversation is running. They reappear when the conversation stops.

The SSE handler checks `conversation_running` to toggle between the two UI views. Progress calculation reuses the same math as existing playback.

## Testing

New test cases:

- **Script listing** — `GET /api/conversations` returns `.json` files from the conversations subdirectory, ignores non-JSON files.
- **Script validation** — `POST /api/conversation/start` rejects: missing files, invalid JSON, missing `turns` key, invalid speaker values (not 1 or 2), references to nonexistent audio files.
- **Start conversation** — starts two loopback processes with correct VirtualSink1/VirtualSink2 names, begins playing first turn on the correct sink.
- **Mutual exclusion** — starting a conversation while single-mic loopback is running stops the loopback first; starting single-mic loopback while conversation is running stops the conversation first.
- **Stop conversation** — kills playback process and both loopback processes, resets state.
- **Turn progression** — after a turn completes, the next turn starts on the correct speaker's sink after the gap.
- **SSE state** — conversation fields are included in the status broadcast with correct values during playback.
- **Conversation completion** — when all turns finish, state resets to idle and loopbacks are torn down.

All tests mock subprocess calls, consistent with the existing test patterns.
