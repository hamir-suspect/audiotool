"""Cross-platform process group creation and teardown."""

import asyncio
import os
import platform
import signal
import subprocess


def shell_kwargs() -> dict:
    """Extra kwargs for create_subprocess_shell to enable process-group control."""
    if platform.system() == "Windows":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


async def kill_process_group(process) -> None:
    """Kill a subprocess and its entire process group, then wait for exit."""
    if platform.system() == "Windows":
        kill = await asyncio.create_subprocess_exec(
            "taskkill", "/T", "/F", "/PID", str(process.pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await kill.wait()
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
    await process.wait()
