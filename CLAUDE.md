# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Audio Router — a FastAPI web app for managing virtual audio devices and simulating multi-participant conversations. Used to test video conferencing apps (Google Meet, Zoom) by routing audio through virtual microphones. Supports Linux (PipeWire/PulseAudio) and Windows (VB-Cable + sounddevice).

## Commands

```bash
make install          # Install system deps (ffmpeg, pipewire, pulseaudio-utils) + check Python packages
make run              # Start uvicorn on host/port from config.json
make test             # Run full test suite
python3 -m pytest tests/test_app.py -v          # Run a single test file
python3 -m pytest tests/test_app.py::test_name -v  # Run a single test
```

API keys (ELEVENLABS_API_KEY, DEEPGRAM_API_KEY) are loaded from `.env`.

## Architecture

**Backend** (`app.py`): FastAPI async app with three independent state objects:
- `AppState` — loopback, playback position, volume, speed
- `ConversationState` — multi-speaker conversation sequencing
- `GenerationState` — TTS generation progress

State changes broadcast to the frontend via **Server-Sent Events** (`/api/status`). Single-mic loopback and conversation mode are mutually exclusive — starting one cancels the other.

**Audio backend** (`audio/`): Abstract `AudioBackend` interface (`base.py`) with platform implementations. Linux uses `pw-loopback`, `pactl`, `paplay`, `ffmpeg` subprocesses. Windows uses VB-Cable + `sounddevice`. Backend is selected at import time in `audio/__init__.py`.

**TTS** (`tts.py`): Abstract provider interface with ElevenLabs and Deepgram implementations. Voice pools with round-robin assignment per speaker.

**Transcript parsing** (`transcript.py`): Parses `Speaker: text` dialogue format into structured turns, assigns speakers to numbered positions, and builds playback script JSON.

**Frontend** (`static/`): Vanilla JS + HTML. Uses `EventSource` for real-time state updates. No build step.

**Config** (`config.py`): Persistent JSON config with platform-aware defaults, validated on update. Stored in `config.json`.

## Testing

Tests use pytest with `@pytest.mark.anyio` for async tests. The test suite mocks the audio backend — no real audio devices needed. Key fixtures: `mock_config` (temp config file), `mock_backend` (patched audio backend), `client` (FastAPI TestClient), `samples_dir` (temp audio directory).
