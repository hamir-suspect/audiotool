"""Windows audio backend — VB-CABLE, sounddevice, pycaw."""

import asyncio
import os
import subprocess
import sys

from .base import AudioBackend, PlaybackHandle


class WindowsAudioBackend(AudioBackend):
    supports_dynamic_device_creation = False

    async def create_virtual_sink(
        self, name, description, mic_name, mic_description,
        *, passive=False, capture_target=None,
    ):
        # VB-CABLE is pre-installed by the user; nothing to create at runtime.
        return None

    async def destroy_virtual_sink(self, process) -> None:
        pass  # Nothing to tear down.

    async def list_sinks(self) -> list[str]:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-list_devices", "true", "-f", "dshow", "-i", "dummy",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        sinks = []
        for line in stderr.decode(errors="replace").splitlines():
            if "audio" in line.lower() and '"' in line:
                start = line.index('"') + 1
                end = line.index('"', start)
                sinks.append(line[start:end])
        return sinks

    async def list_virtual_cables(self) -> list[dict]:
        sinks = await self.list_sinks()
        return [
            {"name": s}
            for s in sinks
            if "cable" in s.lower() or "vb-audio" in s.lower()
        ]

    async def set_source_volume(self, source_name: str, percent: int) -> None:
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            from ctypes import cast, POINTER

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            # pycaw scalar is 0.0–1.0; clamp at 100 %
            volume.SetMasterVolumeLevelScalar(min(percent, 100) / 100.0, None)
        except Exception:
            # Fallback: nircmd or silently skip
            pass

    async def start_playback(
        self, filepath, device: str, position: float, speed: float,
        *, sample_rate: int = 48000, channels: int = 2,
    ) -> PlaybackHandle:
        play_device = os.path.join(os.path.dirname(__file__), "play_device.py")
        ss_arg = f"-ss {position}" if position > 0 else ""
        cmd = (
            f'ffmpeg {ss_arg} -i "{filepath}" '
            f"-filter:a atempo={speed} -f s16le -ac {channels} -ar {sample_rate} - 2>NUL "
            f'| "{sys.executable}" "{play_device}" --device "{device}" '
            f"--samplerate {sample_rate} --channels {channels}"
        )
        process = await asyncio.create_subprocess_shell(
            cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        return PlaybackHandle(process)
