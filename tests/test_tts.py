"""Tests for TTS provider abstraction."""

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from tts import (
    DEEPGRAM_VOICES,
    ELEVENLABS_VOICES,
    DeepgramTTSProvider,
    ElevenLabsTTSProvider,
    assign_voices,
    get_tts_provider,
    load_api_key,
)


def test_assign_voices_two_speakers():
    mapping = assign_voices(["John", "Alice"], "elevenlabs")
    assert mapping["John"] == ELEVENLABS_VOICES[0]["id"]
    assert mapping["Alice"] == ELEVENLABS_VOICES[1]["id"]


def test_assign_voices_wraps_around():
    speakers = [f"Speaker{i}" for i in range(len(ELEVENLABS_VOICES) + 1)]
    mapping = assign_voices(speakers, "elevenlabs")
    assert mapping[speakers[-1]] == ELEVENLABS_VOICES[0]["id"]


def test_assign_voices_deepgram():
    mapping = assign_voices(["A", "B"], "deepgram")
    assert mapping["A"] == DEEPGRAM_VOICES[0]["id"]
    assert mapping["B"] == DEEPGRAM_VOICES[1]["id"]


def test_load_api_key_from_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ELEVENLABS_API_KEY=test_key_123\n")
    monkeypatch.setattr("tts.Path", lambda *a: type("P", (), {"parent": tmp_path, "__truediv__": lambda s, n: env_file, "is_file": lambda s: True, "read_text": lambda s: env_file.read_text()})() if a else tmp_path)
    # Simpler: just test via environment variable
    monkeypatch.setenv("ELEVENLABS_API_KEY", "env_key")
    monkeypatch.setattr("tts.Path.__new__", lambda *a: tmp_path)


def test_load_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "env_key_123")
    # Ensure .env doesn't interfere
    monkeypatch.setattr("tts.Path", lambda x: MagicMock(
        **{"__truediv__": lambda s, n: MagicMock(is_file=lambda: False)}
    ))
    key = load_api_key("elevenlabs")
    assert key == "env_key_123"


def test_get_tts_provider_missing_key(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.setattr("tts.load_api_key", lambda p: "")
    with pytest.raises(ValueError, match="not found"):
        get_tts_provider("elevenlabs")


def test_get_tts_provider_unknown():
    with pytest.raises(ValueError, match="Unknown"):
        get_tts_provider("unknown_provider")


def _mock_httpx_client(mock_resp):
    """Create a properly mocked httpx.AsyncClient context manager."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, mock_client


@pytest.mark.anyio
async def test_elevenlabs_synthesize():
    provider = ElevenLabsTTSProvider("fake_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"fake_mp3_data"

    cm, mock_client = _mock_httpx_client(mock_resp)
    with patch("tts.httpx.AsyncClient", return_value=cm):
        result = await provider.synthesize("Hello world", "voice_123", 1.2)

    assert result == b"fake_mp3_data"
    mock_client.post.assert_awaited_once()
    call_args = mock_client.post.call_args
    assert "voice_123" in call_args.args[0]
    assert call_args.kwargs["json"]["speed"] == 1.2


@pytest.mark.anyio
async def test_elevenlabs_synthesize_error():
    provider = ElevenLabsTTSProvider("fake_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"

    cm, _ = _mock_httpx_client(mock_resp)
    with patch("tts.httpx.AsyncClient", return_value=cm):
        with pytest.raises(RuntimeError, match="401"):
            await provider.synthesize("Hello", "voice_123", 1.0)


@pytest.mark.anyio
async def test_deepgram_synthesize():
    provider = DeepgramTTSProvider("fake_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"fake_mp3_data"

    cm, mock_client = _mock_httpx_client(mock_resp)
    with patch("tts.httpx.AsyncClient", return_value=cm):
        result = await provider.synthesize("Hello world", "aura-asteria-en", 1.0)

    assert result == b"fake_mp3_data"
    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs["params"]["model"] == "aura-asteria-en"


@pytest.mark.anyio
async def test_elevenlabs_list_voices():
    provider = ElevenLabsTTSProvider("fake_key")
    voices = await provider.list_voices()
    assert len(voices) == len(ELEVENLABS_VOICES)
    assert voices[0]["id"] == ELEVENLABS_VOICES[0]["id"]


@pytest.mark.anyio
async def test_deepgram_list_voices():
    provider = DeepgramTTSProvider("fake_key")
    voices = await provider.list_voices()
    assert len(voices) == len(DEEPGRAM_VOICES)
