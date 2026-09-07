"""Audio backend abstraction — platform-specific at runtime."""

import platform

from .base import AudioBackend, PlaybackHandle  # noqa: F401


def get_backend() -> AudioBackend:
    system = platform.system()
    if system == "Windows":
        from .windows import WindowsAudioBackend
        return WindowsAudioBackend()
    if system == "Darwin":
        from .macos import MacOSAudioBackend
        return MacOSAudioBackend()
    from .linux import LinuxAudioBackend
    return LinuxAudioBackend()
