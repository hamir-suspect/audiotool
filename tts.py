"""TTS provider abstraction for ElevenLabs and Deepgram."""

import os
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

# Default voice pools — pre-made voices for round-robin assignment
ELEVENLABS_VOICES = [
    {"id": "onwK4e9ZLuTAKqWW03F9", "name": "Daniel"},
    {"id": "IKne3meq5aSn9XLyUdCD", "name": "Charlie"},
    {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel"},
    {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam"},
    {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella"},
]

DEEPGRAM_VOICES = [
    {"id": "aura-asteria-en", "name": "Asteria"},
    {"id": "aura-luna-en", "name": "Luna"},
    {"id": "aura-orion-en", "name": "Orion"},
    {"id": "aura-arcas-en", "name": "Arcas"},
    {"id": "aura-perseus-en", "name": "Perseus"},
    {"id": "aura-angus-en", "name": "Angus"},
]


def load_api_key(provider: str) -> str:
    """Load API key from .env file or environment."""
    key_name = "ELEVENLABS_API_KEY" if provider == "elevenlabs" else "DEEPGRAM_API_KEY"
    env_file = Path(__file__).parent / ".env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(key_name):
                _, _, val = line.partition("=")
                val = val.strip().strip("'\"")
                if val:
                    return val
    return os.environ.get(key_name, "")


def assign_voices(speakers: list[str], provider: str) -> dict[str, str]:
    """Assign a voice ID to each speaker name from the default pool (round-robin)."""
    pool = ELEVENLABS_VOICES if provider == "elevenlabs" else DEEPGRAM_VOICES
    mapping: dict[str, str] = {}
    for i, name in enumerate(speakers):
        mapping[name] = pool[i % len(pool)]["id"]
    return mapping


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, voice: str, speed: float) -> bytes:
        """Synthesize text to audio bytes (MP3)."""

    @abstractmethod
    async def list_voices(self) -> list[dict]:
        """Return available voices as [{"id": ..., "name": ...}]."""


class ElevenLabsTTSProvider(TTSProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def synthesize(self, text: str, voice: str, speed: float) -> bytes:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                headers={"xi-api-key": self.api_key, "Content-Type": "application/json"},
                json={
                    "text": text,
                    "model_id": "eleven_turbo_v2",
                    "speed": speed,
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
            )
            if not (200 <= resp.status_code < 300):
                raise RuntimeError(f"ElevenLabs API error {resp.status_code}: {resp.text}")
            return resp.content

    async def list_voices(self) -> list[dict]:
        return list(ELEVENLABS_VOICES)


class DeepgramTTSProvider(TTSProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def synthesize(self, text: str, voice: str, speed: float) -> bytes:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.deepgram.com/v1/speak",
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "application/json",
                },
                params={"model": voice, "encoding": "mp3"},
                json={"text": text},
            )
            if not (200 <= resp.status_code < 300):
                raise RuntimeError(f"Deepgram API error {resp.status_code}: {resp.text}")
            return resp.content

    async def list_voices(self) -> list[dict]:
        return list(DEEPGRAM_VOICES)


def get_tts_provider(provider: str) -> TTSProvider:
    """Create a TTS provider instance, loading the API key from .env/environment."""
    if provider not in ("elevenlabs", "deepgram"):
        raise ValueError(f"Unknown TTS provider: {provider}")
    api_key = load_api_key(provider)
    if not api_key:
        key_name = "ELEVENLABS_API_KEY" if provider == "elevenlabs" else "DEEPGRAM_API_KEY"
        raise ValueError(f"{key_name} not found in .env or environment")
    if provider == "elevenlabs":
        return ElevenLabsTTSProvider(api_key)
    else:
        return DeepgramTTSProvider(api_key)
