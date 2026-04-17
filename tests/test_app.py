import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_config(monkeypatch, tmp_path):
    """Provide a test config that points samples_dir to tmp_path."""
    import config as config_module

    test_data = dict(config_module.DEFAULTS)
    test_data["samples_dir"] = str(tmp_path)
    test_data["virtual_sink_name"] = "VirtualSink"
    test_data["virtual_mic_name"] = "VirtualMic"
    test_data["conversation_sink1_name"] = "VirtualSink1"
    test_data["conversation_sink2_name"] = "VirtualSink2"
    test_data["conversation_mic1_name"] = "VirtualMic1"
    test_data["conversation_mic2_name"] = "VirtualMic2"

    # Redirect CONFIG_PATH so save() doesn't write to the real config.json
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.json")

    cfg = config_module.Config.__new__(config_module.Config)
    cfg._data = test_data
    monkeypatch.setattr(config_module, "config", cfg)

    import app as app_module
    monkeypatch.setattr(app_module, "config", cfg)
    return cfg


@pytest.fixture
def mock_backend(monkeypatch):
    """Replace app.backend with a mock implementing AudioBackend."""
    import app as app_module

    mock = MagicMock()
    mock.supports_dynamic_device_creation = True
    mock.create_virtual_sink = AsyncMock(return_value=MagicMock())
    mock.destroy_virtual_sink = AsyncMock()
    mock.list_sinks = AsyncMock(return_value=[])
    mock.list_virtual_cables = AsyncMock(return_value=[])
    mock.set_source_volume = AsyncMock()
    mock.get_duration = AsyncMock(return_value=0.0)

    def _make_handle():
        h = MagicMock()
        h.pid = 12345
        h.kill = AsyncMock()
        h.wait = AsyncMock(return_value=0)
        return h

    mock._make_handle = _make_handle
    mock.start_playback = AsyncMock(side_effect=lambda *a, **kw: _make_handle())
    monkeypatch.setattr(app_module, "backend", mock)
    return mock


@pytest.fixture
def samples_dir(mock_config):
    """Return the tmp_path used by mock_config as samples_dir."""
    from pathlib import Path
    return Path(mock_config["samples_dir"])


@pytest.fixture
def client(mock_backend, mock_config):
    from app import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    from app import state, conv_state, gen_state
    state.__init__()
    conv_state.__init__()
    gen_state.__init__()
    yield


@pytest.mark.anyio
async def test_status_sse_includes_conversation_fields(mock_backend, mock_config):
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
    assert "conversation_gap_min" in data
    assert "conversation_gap_max" in data
    assert data["conversation_playback_duration"] == 0
    assert data["conversation_playback_started_at"] == 0


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


def test_conversation_start_success(samples_dir, client, mock_backend):
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

    handle = MagicMock()
    handle.pid = 12345
    handle.kill = AsyncMock()

    async def _wait_forever():
        await asyncio.Future()

    handle.wait = _wait_forever
    mock_backend.start_playback = AsyncMock(return_value=handle)

    resp = client.post("/api/conversation/start", json={"script": "chat.json"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"

    from app import conv_state
    assert conv_state.running is True
    assert conv_state.script == "chat.json"
    assert conv_state.gap_min == 1.5
    assert conv_state.gap_max == 1.5
    assert len(conv_state.turns) == 2


@pytest.mark.anyio
async def test_conversation_turn_execution(samples_dir, mock_backend, mock_config):
    from app import conv_state, _run_conversation

    (samples_dir / "a.mp3").write_bytes(b"fake")
    (samples_dir / "b.mp3").write_bytes(b"fake")

    conv_state.running = True
    conv_state.script = "test.json"
    conv_state.turns = [
        {"speaker": 1, "file": "a.mp3"},
        {"speaker": 2, "file": "b.mp3"},
    ]
    conv_state.gap_min = 0.0
    conv_state.gap_max = 0.0
    conv_state.loopback1_process = MagicMock()
    conv_state.loopback2_process = MagicMock()

    mock_backend.get_duration = AsyncMock(return_value=5.0)

    handle = MagicMock()
    handle.pid = 12345
    handle.wait = AsyncMock(return_value=0)
    handle.kill = AsyncMock()
    mock_backend.start_playback = AsyncMock(return_value=handle)

    await _run_conversation()

    assert mock_backend.start_playback.call_count == 2
    calls = mock_backend.start_playback.call_args_list
    assert calls[0].args[1] == "VirtualSink1"
    assert calls[1].args[1] == "VirtualSink2"
    assert conv_state.running is False


@pytest.mark.anyio
async def test_conversation_completion_preserves_loopbacks(samples_dir, mock_backend, mock_config):
    from app import conv_state, _run_conversation

    (samples_dir / "a.mp3").write_bytes(b"fake")

    conv_state.running = True
    conv_state.turns = [{"speaker": 1, "file": "a.mp3"}]
    conv_state.gap_min = 0.0
    conv_state.gap_max = 0.0

    mock_lb1 = MagicMock()
    mock_lb2 = MagicMock()
    conv_state.loopback1_process = mock_lb1
    conv_state.loopback2_process = mock_lb2
    conv_state.loopbacks_ready = True

    mock_backend.get_duration = AsyncMock(return_value=5.0)
    handle = MagicMock()
    handle.pid = 12345
    handle.wait = AsyncMock(return_value=0)
    handle.kill = AsyncMock()
    mock_backend.start_playback = AsyncMock(return_value=handle)

    await _run_conversation()

    mock_backend.destroy_virtual_sink.assert_not_called()
    assert conv_state.loopback1_process is mock_lb1
    assert conv_state.loopback2_process is mock_lb2
    assert conv_state.loopbacks_ready is True


@pytest.mark.anyio
async def test_conversation_stop(mock_backend, mock_config):
    from app import conv_state, stop_conversation

    handle = MagicMock()
    handle.pid = 12345
    handle.kill = AsyncMock()
    handle.wait = AsyncMock()

    mock_lb1 = MagicMock()
    mock_lb2 = MagicMock()

    conv_state.running = True
    conv_state.script = "chat.json"
    conv_state.turns = [{"speaker": 1, "file": "a.mp3"}]
    conv_state.current_turn = 0
    conv_state.playback_process = handle
    conv_state.loopback1_process = mock_lb1
    conv_state.loopback2_process = mock_lb2
    conv_state.loopbacks_ready = True
    conv_state._task = asyncio.create_task(asyncio.sleep(999))

    resp = await stop_conversation()

    assert resp["status"] == "stopped"
    assert conv_state.running is False
    assert conv_state.playback_process is None
    handle.kill.assert_awaited_once()
    assert conv_state.loopback1_process is mock_lb1


def test_conversation_stop_not_running(client):
    resp = client.post("/api/conversation/stop")
    assert "error" in resp.json()


@pytest.mark.anyio
async def test_start_loopback_stops_conversation(mock_backend, mock_config):
    from app import conv_state, start_loopback, LoopbackStartRequest

    mock_lb = MagicMock()
    conv_state.running = True
    conv_state.loopback1_process = mock_lb
    conv_state.loopback2_process = mock_lb
    conv_state._task = asyncio.create_task(asyncio.sleep(999))

    resp = await start_loopback(LoopbackStartRequest(mode="virtual-sink"))

    assert resp["status"] == "started"
    assert conv_state.running is False


def test_start_conversation_stops_loopback(samples_dir, client, mock_backend):
    from app import state

    conv_dir = samples_dir / "conversations"
    conv_dir.mkdir()
    (samples_dir / "a.mp3").write_bytes(b"fake")
    script = {"turns": [{"speaker": 1, "file": "a.mp3"}]}
    (conv_dir / "chat.json").write_text(json.dumps(script))

    state.loopback_running = True
    state.loopback_process = MagicMock()

    handle = MagicMock()
    handle.pid = 12345
    handle.kill = AsyncMock()

    async def _wait_forever():
        await asyncio.Future()

    handle.wait = _wait_forever
    mock_backend.start_playback = AsyncMock(return_value=handle)

    resp = client.post("/api/conversation/start", json={"script": "chat.json"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    assert state.loopback_running is False
    mock_backend.destroy_virtual_sink.assert_awaited()


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


def test_list_sinks(client, mock_backend):
    mock_backend.list_sinks = AsyncMock(return_value=[
        "alsa_output.pci-0000_00_1f.3.analog-stereo",
        "alsa_output.usb",
    ])

    resp = client.get("/api/sinks")

    assert resp.status_code == 200
    assert resp.json()["sinks"] == [
        "alsa_output.pci-0000_00_1f.3.analog-stereo",
        "alsa_output.usb",
    ]


@pytest.mark.anyio
async def test_status_sse_returns_initial_state(mock_backend, mock_config):
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
    assert response.media_type == "text/event-stream"

    first_event = None
    async for chunk in response.body_iterator:
        if chunk.startswith("data: "):
            first_event = chunk
            break

    assert first_event is not None
    data = json.loads(first_event[6:].strip())
    assert data["loopback_running"] is False
    assert data["loopback_mode"] == "virtual-sink"
    assert data["current_file"] is None
    assert data["playback_speed"] == 1.0
    assert data["playback_position"] == 0.0


def test_loopback_start_virtual_sink(client, mock_backend):
    resp = client.post("/api/loopback/start", json={"mode": "virtual-sink"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    assert resp.json()["mode"] == "virtual-sink"
    mock_backend.create_virtual_sink.assert_awaited_once()


def test_loopback_start_sink_capture(client, mock_backend):
    resp = client.post("/api/loopback/start", json={"mode": "sink-capture", "sink": "alsa_output.usb"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    assert resp.json()["mode"] == "sink-capture"
    call_kwargs = mock_backend.create_virtual_sink.call_args
    assert call_kwargs.kwargs.get("capture_target") == "alsa_output.usb"


def test_loopback_start_sink_capture_requires_sink(client):
    resp = client.post("/api/loopback/start", json={"mode": "sink-capture"})
    assert "error" in resp.json()


def test_loopback_start_already_running(client):
    from app import state
    state.loopback_running = True

    resp = client.post("/api/loopback/start", json={"mode": "virtual-sink"})
    assert resp.json()["error"] == "Loopback already running"


def test_loopback_stop(client, mock_backend):
    from app import state
    state.loopback_running = True
    state.loopback_process = MagicMock()

    resp = client.post("/api/loopback/stop")

    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
    mock_backend.destroy_virtual_sink.assert_awaited_once()


def test_loopback_stop_not_running(client):
    resp = client.post("/api/loopback/stop")
    assert resp.json()["error"] == "Loopback not running"


def test_play_file(samples_dir, client, mock_backend):
    (samples_dir / "song.mp3").write_bytes(b"fake audio")
    from app import state
    state.loopback_running = True
    state.loopback_mode = "virtual-sink"

    mock_backend.get_duration = AsyncMock(return_value=120.5)

    resp = client.post("/api/play", json={"filename": "song.mp3"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "playing"
    assert resp.json()["filename"] == "song.mp3"
    mock_backend.get_duration.assert_awaited_once()
    mock_backend.start_playback.assert_awaited_once()


def test_play_requires_virtual_sink_mode(client):
    from app import state
    state.loopback_running = True
    state.loopback_mode = "sink-capture"

    resp = client.post("/api/play", json={"filename": "song.mp3"})
    assert "error" in resp.json()


def test_play_requires_loopback_running(client):
    resp = client.post("/api/play", json={"filename": "song.mp3"})
    assert "error" in resp.json()


def test_stop_playback(client, mock_backend):
    from app import state
    handle = MagicMock()
    handle.pid = 12345
    handle.kill = AsyncMock()
    handle.wait = AsyncMock()
    state.playback_process = handle
    state.current_file = "song.mp3"

    resp = client.post("/api/stop")

    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
    handle.kill.assert_awaited_once()


def test_stop_nothing_playing(client):
    resp = client.post("/api/stop")
    assert resp.json()["error"] == "Nothing playing"


def test_set_volume(client, mock_backend):
    resp = client.post("/api/volume", json={"percent": 150})

    assert resp.status_code == 200
    assert resp.json()["percent"] == 150
    mock_backend.set_source_volume.assert_awaited_once_with("VirtualMic", 150)


@pytest.mark.anyio
async def test_kill_playback_preserve_metadata(mock_backend, mock_config):
    from app import state, _kill_playback

    handle = MagicMock()
    handle.pid = 12345
    handle.kill = AsyncMock()
    handle.wait = AsyncMock()

    state.playback_process = handle
    state.current_file = "song.mp3"
    state.playback_duration = 120.5
    state.playback_started_at = 1000.0
    state.playback_position = 30.0
    state.playback_speed = 1.5
    state.current_filepath = "/path/to/song.mp3"

    await _kill_playback(preserve_metadata=True)

    assert state.playback_process is None
    assert state.current_file == "song.mp3"
    assert state.playback_duration == 120.5
    assert state.playback_speed == 1.5
    assert state.current_filepath == "/path/to/song.mp3"
    handle.kill.assert_awaited_once()


def test_play_resets_speed(samples_dir, client, mock_backend):
    from app import state
    state.loopback_running = True
    state.loopback_mode = "virtual-sink"
    state.playback_speed = 1.5

    (samples_dir / "song.mp3").write_bytes(b"fake audio")
    mock_backend.get_duration = AsyncMock(return_value=120.5)

    resp = client.post("/api/play", json={"filename": "song.mp3"})

    assert resp.status_code == 200
    assert state.playback_speed == 1.0
    assert state.playback_position == 0.0


def test_set_speed_no_playback(client):
    resp = client.post("/api/speed", json={"speed": 1.5})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["speed"] == 1.5

    from app import state
    assert state.playback_speed == 1.5


def test_set_speed_invalid(client):
    resp = client.post("/api/speed", json={"speed": 3.0})
    assert "error" in resp.json()

    resp = client.post("/api/speed", json={"speed": 0.0})
    assert "error" in resp.json()


def test_set_speed_during_playback(client, mock_backend):
    from app import state

    handle = MagicMock()
    handle.pid = 12345
    handle.kill = AsyncMock()
    handle.wait = AsyncMock()

    state.playback_process = handle
    state.current_file = "song.mp3"
    state.current_filepath = "/tmp/song.mp3"
    state.playback_duration = 120.0
    state.playback_speed = 1.0
    state.playback_position = 0.0
    state.playback_started_at = 1000.0

    new_handle = MagicMock()
    new_handle.pid = 99999
    new_handle.kill = AsyncMock()

    async def _wait_forever():
        await asyncio.Future()

    new_handle.wait = _wait_forever
    mock_backend.start_playback = AsyncMock(return_value=new_handle)

    with patch("app.time.time", return_value=1010.0):
        resp = client.post("/api/speed", json={"speed": 1.5})

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert state.playback_position == 10.0
    assert state.playback_speed == 1.5
    assert state.current_file == "song.mp3"

    call_args = mock_backend.start_playback.call_args
    assert call_args.args[2] == 10.0
    assert call_args.args[3] == 1.5


def test_set_speed_near_end_stops(client, mock_backend):
    from app import state

    handle = MagicMock()
    handle.pid = 12345
    handle.kill = AsyncMock()
    handle.wait = AsyncMock()

    state.playback_process = handle
    state.current_file = "song.mp3"
    state.current_filepath = "/tmp/song.mp3"
    state.playback_duration = 60.0
    state.playback_speed = 2.0
    state.playback_position = 50.0
    state.playback_started_at = 1000.0

    with patch("app.time.time", return_value=1006.0):
        resp = client.post("/api/speed", json={"speed": 1.0})

    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
    assert state.current_file is None
    assert state.playback_speed == 1.0


def test_capabilities(client, mock_backend):
    mock_backend.list_virtual_cables = AsyncMock(return_value=[])

    resp = client.get("/api/capabilities")

    assert resp.status_code == 200
    data = resp.json()
    assert data["platform"] in ("Linux", "Windows", "Darwin")
    assert data["supports_dynamic_device_creation"] is True
    assert data["virtual_cables"] == []


def test_get_config(client, mock_config):
    resp = client.get("/api/config")

    assert resp.status_code == 200
    data = resp.json()
    assert data["virtual_sink_name"] == "VirtualSink"
    assert data["sample_rate"] == 48000
    assert isinstance(data["allowed_speeds"], list)


def test_update_config(client, mock_config):
    resp = client.put("/api/config", json={"default_volume": 200, "sample_rate": 44100})

    assert resp.status_code == 200
    data = resp.json()
    assert data["default_volume"] == 200
    assert data["sample_rate"] == 44100


def test_update_config_validation(client, mock_config):
    resp = client.put("/api/config", json={"channels": 5})

    assert resp.status_code == 200
    data = resp.json()
    assert "errors" in data


# --- Generation endpoint tests ---


def test_generate_parse_basic(client):
    resp = client.post("/api/generate/parse", json={"text": "John: Hello\nAlice: Hi there"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["speakers"] == ["John", "Alice"]
    assert len(data["turns"]) == 2
    assert data["turns"][0]["speaker"] == "John"
    assert data["turns"][0]["text"] == "Hello"


def test_generate_parse_empty(client):
    resp = client.post("/api/generate/parse", json={"text": ""})
    assert "error" in resp.json()


def test_generate_parse_no_valid_format(client):
    resp = client.post("/api/generate/parse", json={"text": "just random text"})
    assert "error" in resp.json()


def test_generate_tts_missing_speaker_mapping(client, samples_dir):
    resp = client.post("/api/generate/tts", json={
        "name": "test-conv",
        "turns": [{"speaker": "John", "text": "hi"}],
        "speaker_mapping": {},
        "provider": "elevenlabs",
    })
    assert "error" in resp.json()
    assert "John" in resp.json()["error"]


def test_generate_tts_invalid_speaker_mapping(client, samples_dir):
    resp = client.post("/api/generate/tts", json={
        "name": "test-conv",
        "turns": [{"speaker": "John", "text": "hi"}],
        "speaker_mapping": {"John": 3},
        "provider": "elevenlabs",
    })
    assert "error" in resp.json()
    assert "1 or 2" in resp.json()["error"]


def test_generate_tts_duplicate_name(client, samples_dir):
    conv_dir = samples_dir / "conversations" / "existing"
    conv_dir.mkdir(parents=True)

    resp = client.post("/api/generate/tts", json={
        "name": "existing",
        "turns": [{"speaker": "John", "text": "hi"}],
        "speaker_mapping": {"John": 1},
        "provider": "elevenlabs",
    })
    assert "error" in resp.json()
    assert "already exists" in resp.json()["error"]


def test_generate_tts_missing_api_key(client, samples_dir, monkeypatch):
    monkeypatch.setattr("app.get_tts_provider", lambda p: (_ for _ in ()).throw(ValueError("KEY not found")))
    resp = client.post("/api/generate/tts", json={
        "name": "test-conv",
        "turns": [{"speaker": "John", "text": "hi"}],
        "speaker_mapping": {"John": 1},
        "provider": "elevenlabs",
    })
    assert "error" in resp.json()
    assert "not found" in resp.json()["error"]


def test_generate_cancel_not_running(client):
    resp = client.post("/api/generate/cancel")
    assert "error" in resp.json()


@pytest.mark.anyio
async def test_sse_includes_generation_fields(mock_backend, mock_config):
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
    assert data["gen_active"] is False
    assert data["gen_step"] is None
    assert data["gen_tts_total"] == 0
    assert data["gen_tts_completed"] == 0
    assert data["gen_error"] is None
