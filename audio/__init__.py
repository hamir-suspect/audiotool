"""Audio backend abstraction — platform-specific at runtime."""

import platform

from .base import AudioBackend, PlaybackHandle  # noqa: F401


def get_backend() -> AudioBackend:
    if platform.system() == "Windows":
        from .windows import WindowsAudioBackend
        return WindowsAudioBackend()
    from .linux import LinuxAudioBackend
    return LinuxAudioBackend()
