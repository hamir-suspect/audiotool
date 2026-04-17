"""AudioBackend ABC and PlaybackHandle."""

import asyncio
from abc import ABC, abstractmethod

from .process import kill_process_group


class PlaybackHandle:
    """Wraps an asyncio subprocess with a cross-platform kill() method."""

    def __init__(self, process):
        self.process = process
        self.pid = process.pid

    async def kill(self):
        await kill_process_group(self.process)

    async def wait(self):
        return await self.process.wait()


class AudioBackend(ABC):
    supports_dynamic_device_creation: bool

    @abstractmethod
    async def create_virtual_sink(
        self, name, description, mic_name, mic_description,
        *, passive=False, capture_target=None,
    ):
        """Create a virtual audio sink/mic pair.

        Returns the backing process (Linux) or None (Windows, pre-installed).
        When *capture_target* is set, capture from that existing sink instead
        of creating a new one.
        """

    @abstractmethod
    async def destroy_virtual_sink(self, process) -> None:
        """Tear down a virtual sink created by create_virtual_sink."""

    @abstractmethod
    async def list_sinks(self) -> list[str]:
        """Enumerate available audio sinks."""

    @abstractmethod
    async def list_virtual_cables(self) -> list[dict]:
        """Discover pre-installed virtual-cable devices (Windows)."""

    @abstractmethod
    async def set_source_volume(self, source_name: str, percent: int) -> None:
        """Set the volume of an audio source."""

    @abstractmethod
    async def start_playback(
        self, filepath, device: str, position: float, speed: float,
        *, sample_rate: int = 48000, channels: int = 2,
    ) -> PlaybackHandle:
        """Start an ffmpeg playback pipeline targeting *device*."""

    async def get_duration(self, filepath) -> float:
        """Return the duration of an audio file in seconds (via ffprobe)."""
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(filepath),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        try:
            return float(stdout.decode().strip())
        except ValueError:
            return 0.0
