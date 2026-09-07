"""macOS audio backend — BlackHole + sounddevice."""

import asyncio
import os
import re
import shlex
import sys

from .base import AudioBackend, PlaybackHandle


class MacOSAudioBackend(AudioBackend):
    supports_dynamic_device_creation = False

    async def create_virtual_sink(
        self, name, description, mic_name, mic_description,
        *, passive=False, capture_target=None,
    ):
        return None

    async def destroy_virtual_sink(self, process) -> None:
        pass

    async def list_sinks(self) -> list[str]:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", "",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        sinks = []
        in_audio = False
        for line in stderr.decode(errors="replace").splitlines():
            if "AVFoundation audio devices:" in line:
                in_audio = True
                continue
            if not in_audio:
                continue
            m = re.search(r"\]\s*\[\d+]\s*(.+)$", line)
            if m:
                sinks.append(m.group(1).strip())
            else:
                break
        return sinks

    async def list_virtual_cables(self) -> list[dict]:
        sinks = await self.list_sinks()
        return [
            {"name": s}
            for s in sinks
            if "blackhole" in s.lower()
        ]

    async def set_source_volume(self, source_name: str, percent: int) -> None:
        vol = max(0, min(percent, 100))
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", f"set volume output volume {vol}",
        )
        await proc.wait()

    async def start_playback(
        self, filepath, device: str, position: float, speed: float,
        *, sample_rate: int = 48000, channels: int = 2,
    ) -> PlaybackHandle:
        play_device = os.path.join(os.path.dirname(__file__), "play_device.py")
        ss_arg = f"-ss {position}" if position > 0 else ""
        cmd = (
            f"ffmpeg {ss_arg} -i {shlex.quote(str(filepath))} "
            f"-filter:a atempo={speed} -f s16le -ac {channels} -ar {sample_rate} - 2>/dev/null "
            f"| {shlex.quote(sys.executable)} {shlex.quote(play_device)} --device {shlex.quote(device)} "
            f"--samplerate {sample_rate} --channels {channels}"
        )
        process = await asyncio.create_subprocess_shell(
            cmd, start_new_session=True,
        )
        return PlaybackHandle(process)
