# Audio Router

A FastAPI web app for managing virtual audio devices and simulating multi-participant conversations. Used to test video conferencing apps (Google Meet, Zoom) by routing audio through virtual microphones.

Supports Linux (PipeWire/PulseAudio) and Windows (VB-Cable + sounddevice).

## Setup

### Prerequisites

**Linux:** ffmpeg, PipeWire, PulseAudio utilities (`pw-loopback`, `pactl`, `paplay`)

**Windows:** [VB-Cable](https://vb-audio.com/Cable/) virtual audio driver

### Install

```bash
make install
```

This installs system dependencies (Linux) and checks that Python packages are present. Install Python deps with:

```bash
pip install -r requirements.txt
```

### Environment

Create a `.env` file with your API keys:

```
ELEVENLABS_API_KEY=your_key
DEEPGRAM_API_KEY=your_key
```

## Usage

```bash
make run
```

Opens a web UI for:

- **Loopback** — route a virtual mic's audio through PipeWire loopback
- **Playback** — play audio files through a virtual mic with volume/speed control
- **Conversation mode** — sequence multi-speaker TTS audio across virtual mics to simulate a meeting

## Testing

```bash
make test
```

Tests mock the audio backend — no real audio devices needed.

## Project Structure

```
app.py                 # FastAPI application
config.py              # Persistent JSON config
tts.py                 # TTS providers (ElevenLabs, Deepgram)
transcript.py          # Transcript parsing and playback script generation
generate_conversation.py  # Conversation generation workflow
audio/                 # Audio backend implementations
  base.py              #   Abstract interface
  linux.py             #   PipeWire/PulseAudio backend
  windows.py           #   VB-Cable/sounddevice backend
static/                # Frontend (vanilla JS + HTML)
tests/                 # pytest test suite
```
