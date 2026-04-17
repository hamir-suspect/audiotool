# dsoignoo — Audio Router Webapp

## Purpose

A local webapp that provides a UI for:
- Starting/stopping PipeWire loopback (pw-loopback) in two modes
- Browsing and playing audio files into a virtual sink for use as a microphone in apps like Google Meet
- Controlling virtual mic volume

## Tech Stack

- **Backend:** Python + FastAPI
- **Frontend:** Vanilla HTML/JS/CSS (served by FastAPI)
- **Audio:** pw-loopback, ffmpeg, paplay (PipeWire/PulseAudio)
- **Project location:** `~/Documents/dsoignoo/`

## Architecture

Single FastAPI process serving static frontend and managing subprocesses.

```
Browser  ──HTTP──▶  FastAPI  ──subprocess──▶  pw-loopback
                      │                    ▶  ffmpeg | paplay
                      │
                    SSE push (playback state)
```

### Subprocess Management

- **pw-loopback**: Started/stopped on demand. Two modes:
  - **Virtual Sink** (default): `pw-loopback --capture-props='media.class=Audio/Sink node.name=VirtualSink node.description="Virtual Sink"' --playback-props='media.class=Audio/Source node.name=VirtualMic node.description="Virtual Mic"'`
  - **Sink Capture**: `pw-loopback --capture-props='node.target=<selected-sink>' --playback-props='media.class=Audio/Source node.name=VirtualMic node.description="Virtual Mic"'`

- **Audio playback**: `ffmpeg -i <file> -f wav -ac 2 -ar 48000 - 2>/dev/null | paplay --device=VirtualSink`
  - Only available when loopback is running in Virtual Sink mode

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Serve the UI |
| `GET` | `/api/files` | List audio files in `/home/hamir/Documents/samples` |
| `GET` | `/api/sinks` | List available PulseAudio sinks |
| `GET` | `/api/status` | SSE stream — loopback state, current file, playback progress |
| `POST` | `/api/loopback/start` | Start pw-loopback. Body: `{mode: "virtual-sink" | "sink-capture", sink?: "sink-name"}` |
| `POST` | `/api/loopback/stop` | Stop pw-loopback |
| `POST` | `/api/play` | Play file. Body: `{filename: "..."}` |
| `POST` | `/api/stop` | Stop current playback |
| `POST` | `/api/volume` | Set virtual mic volume. Body: `{percent: 300}` |

## UI Layout

Single-page layout with four sections:

1. **Loopback Control** — Mode dropdown (Virtual Sink / Sink Capture), sink dropdown (shown only for Sink Capture mode), Start/Stop buttons, status indicator
2. **Volume** — Slider controlling virtual mic volume (default 300%)
3. **Audio Files** — List of files from `/home/hamir/Documents/samples` with play buttons
4. **Now Playing** — Shown during playback: filename, seek/progress bar, pause/stop controls

## File Structure

```
~/Documents/dsoignoo/
├── app.py              # FastAPI app, subprocess management, API endpoints
├── static/
│   ├── index.html      # Single page UI
│   ├── style.css       # Styling
│   └── app.js          # Frontend logic, SSE handling
├── requirements.txt    # fastapi, uvicorn
└── docs/
```

## Key Behaviors

- Default loopback mode is Virtual Sink
- Volume defaults to 300%
- Audio file list shows files with common audio extensions (.mp3, .wav, .ogg, .mp4, .flac, .m4a)
- Playing a new file stops the currently playing file
- Stopping loopback stops any active playback first
- SSE pushes state updates: loopback running/stopped, mode, current file, playback progress
- Samples directory: `/home/hamir/Documents/samples`
