# Windows Support Plan

## Problem

The app is Linux-only due to:
- `pw-loopback` (PipeWire) for virtual audio devices
- `pactl` / `paplay` (PulseAudio) for sink listing, volume, playback
- `os.killpg` / `os.getpgid` / `start_new_session=True` (Unix process groups)
- Shell pipes (`ffmpeg ... | paplay`)

## Architecture

Strategy pattern: `AudioBackend` ABC with `LinuxAudioBackend` and `WindowsAudioBackend`. Selected at startup via `platform.system()`. The rest of `app.py` calls backend methods instead of raw subprocess commands.

### New file structure

```
audio/
  __init__.py       # get_backend() factory
  base.py           # AudioBackend ABC + PlaybackHandle
  process.py        # Cross-platform process kill / subprocess kwargs
  linux.py          # LinuxAudioBackend (existing behavior, extracted)
  windows.py        # WindowsAudioBackend (VB-CABLE, sounddevice, pycaw)
  play_device.py    # Tiny stdin-to-sounddevice bridge (replaces paplay on Windows)
```

## Platform mapping

| Feature | Linux | Windows |
|---|---|---|
| Virtual device creation | `pw-loopback` (runtime) | VB-CABLE (pre-installed by user) |
| Audio playback to device | `ffmpeg \| paplay --device=X` | `ffmpeg \| python play_device.py --device "CABLE Input"` |
| Sink enumeration | `pactl list short sinks` | `ffmpeg -list_devices true -f dshow -i dummy` |
| Volume control | `pactl set-source-volume` | `pycaw` (Windows Core Audio API) |
| Process group kill | `os.killpg(os.getpgid(pid), SIGTERM)` | `taskkill /T /F /PID` |
| Process group create | `start_new_session=True` | `CREATE_NEW_PROCESS_GROUP` |

## Backend interface

```python
class AudioBackend(ABC):
    supports_dynamic_device_creation: bool  # Linux=True, Windows=False

    async def create_virtual_sink(name, description, mic_name, mic_description, passive=False) -> Process | None
    async def destroy_virtual_sink(process) -> None
    async def list_sinks() -> list[str]
    async def list_virtual_cables() -> list[dict]  # Windows: discovered VB-CABLEs
    async def set_source_volume(source_name, percent) -> None
    async def start_playback(filepath, device, position, speed) -> PlaybackHandle
    async def get_duration(filepath) -> float
```

`PlaybackHandle` wraps a process with a cross-platform `kill()` method.

## Windows device name mapping

VB-CABLE devices have names like:
- `CABLE Input (VB-Audio Virtual Cable)` — the sink
- `CABLE Output (VB-Audio Virtual Cable)` — appears as microphone

For conversation mode (2 speakers), user needs VB-CABLE-A and VB-CABLE-B.

Configured via env vars:
```
VIRTUAL_SINK_DEVICE=CABLE Input (VB-Audio Virtual Cable)
VIRTUAL_MIC_DEVICE=CABLE Output (VB-Audio Virtual Cable)
VIRTUAL_SINK1_DEVICE=CABLE-A Input (VB-Audio Virtual Cable A)
VIRTUAL_SINK2_DEVICE=CABLE-B Input (VB-Audio Virtual Cable B)
```

## `play_device.py` (paplay replacement)

~30 lines. Reads raw WAV from stdin, writes to a named output device via `sounddevice` (PortAudio wrapper). Used on Windows only; Linux keeps `paplay`.

## app.py changes

Mechanical — replace every raw subprocess call with a backend call:
- `list_sinks()` → `backend.list_sinks()`
- `_kill_playback()` → `playback_handle.kill()`
- `_start_playback_pipeline()` → `backend.start_playback()`
- `start_loopback()` → `backend.create_virtual_sink()`
- `stop_loopback()` → `backend.destroy_virtual_sink()`
- `play_file()` duration → `backend.get_duration()`
- `set_volume()` → `backend.set_source_volume()`
- All conversation loopback/playback calls → same pattern

New endpoint:
```python
@app.get("/api/capabilities")
async def capabilities():
    return {
        "platform": platform.system(),
        "supports_dynamic_device_creation": backend.supports_dynamic_device_creation,
        "virtual_cables": await backend.list_virtual_cables(),
    }
```

## Frontend changes

- Fetch `/api/capabilities` at startup
- When `supports_dynamic_device_creation` is false: hide Start/Stop Loopback, show device selection dropdown from `virtual_cables` instead
- Mode selector (virtual-sink vs sink-capture) only shown on Linux

## New dependencies

```
sounddevice    # Windows playback (wraps PortAudio, bundled on Windows pip)
pycaw          # Windows volume control (optional, can use PowerShell fallback)
```

## Implementation order

1. Create `audio/` package with `base.py`, `process.py`
2. Create `audio/linux.py` — extract existing subprocess logic from `app.py`
3. Refactor `app.py` to use `backend = get_backend()` — all tests still pass
4. Create `audio/play_device.py` — stdin-to-sounddevice bridge
5. Create `audio/windows.py` — implement all backend methods
6. Add `/api/capabilities` endpoint
7. Update frontend for conditional UI
8. Update `requirements.txt`
9. Update tests to mock backend interface instead of raw subprocesses
