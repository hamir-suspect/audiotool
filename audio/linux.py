"""Linux audio backend — PipeWire / PulseAudio."""

import asyncio
import shlex

from .base import AudioBackend, PlaybackHandle


class LinuxAudioBackend(AudioBackend):
    supports_dynamic_device_creation = True

    async def create_virtual_sink(
        self, name, description, mic_name, mic_description,
        *, passive=False, capture_target=None,
    ):
        if capture_target:
            cmd = [
                "pw-loopback",
                f"--capture-props=node.target={capture_target}",
                f'--playback-props=media.class=Audio/Source node.name={mic_name} node.description="{mic_description}"',
            ]
        else:
            passive_prop = " node.passive=true" if passive else ""
            cmd = [
                "pw-loopback",
                f'--capture-props=media.class=Audio/Sink node.name={name} node.description="{description}"',
                f'--playback-props=media.class=Audio/Source node.name={mic_name} node.description="{mic_description}"{passive_prop}',
            ]
        return await asyncio.create_subprocess_exec(*cmd)

    async def destroy_virtual_sink(self, process) -> None:
        if process:
            process.terminate()
            await process.wait()

    async def list_sinks(self) -> list[str]:
        proc = await asyncio.create_subprocess_exec(
            "pactl", "list", "short", "sinks",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        sinks = []
        for line in stdout.decode().strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                sinks.append(parts[1])
        return sinks

    async def list_virtual_cables(self) -> list[dict]:
        return []

    async def set_source_volume(self, source_name: str, percent: int) -> None:
        proc = await asyncio.create_subprocess_exec(
            "pactl", "set-source-volume", source_name, f"{percent}%",
        )
        await proc.wait()

    async def start_playback(
        self, filepath, device: str, position: float, speed: float,
        *, sample_rate: int = 48000, channels: int = 2,
    ) -> PlaybackHandle:
        ss_arg = f"-ss {position}" if position > 0 else ""
        cmd = (
            f"ffmpeg {ss_arg} -i {shlex.quote(str(filepath))} "
            f"-filter:a atempo={speed} -f wav -ac {channels} -ar {sample_rate} - 2>/dev/null "
            f"| paplay --device={device}"
        )
        process = await asyncio.create_subprocess_shell(
            cmd, start_new_session=True,
        )
        return PlaybackHandle(process)
