"""Persistent JSON configuration with platform-aware defaults."""

import json
import os
import platform
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

_IS_WINDOWS = platform.system() == "Windows"
_IS_MACOS = platform.system() == "Darwin"

DEFAULTS = {
    "samples_dir": os.environ.get("SAMPLES_DIR", str(Path.home() / "Documents" / "samples")),
    "default_volume": 300,
    "sample_rate": 48000,
    "channels": 2,
    "conversation_gap_min": 0.1,
    "conversation_gap_max": 1.0,
    "allowed_speeds": [0.5, 0.75, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0],
    "host": "127.0.0.1",
    "port": 8000,
    "tts_provider": "deepgram",
    "tts_speed": 1.2,
}

if _IS_WINDOWS:
    DEFAULTS.update({
        "virtual_sink_name": os.environ.get("VIRTUAL_SINK_DEVICE", "CABLE Input (VB-Audio Virtual Cable)"),
        "virtual_mic_name": os.environ.get("VIRTUAL_MIC_DEVICE", "CABLE Output (VB-Audio Virtual Cable)"),
        "conversation_sink1_name": os.environ.get("VIRTUAL_SINK1_DEVICE", "CABLE-A Input (VB-Audio Virtual Cable A)"),
        "conversation_sink2_name": os.environ.get("VIRTUAL_SINK2_DEVICE", "CABLE-B Input (VB-Audio Virtual Cable B)"),
        "conversation_mic1_name": os.environ.get("VIRTUAL_MIC1_DEVICE", "CABLE-A Output (VB-Audio Virtual Cable A)"),
        "conversation_mic2_name": os.environ.get("VIRTUAL_MIC2_DEVICE", "CABLE-B Output (VB-Audio Virtual Cable B)"),
    })
elif _IS_MACOS:
    DEFAULTS.update({
        "virtual_sink_name": os.environ.get("VIRTUAL_SINK_DEVICE", "BlackHole 2ch"),
        "virtual_mic_name": os.environ.get("VIRTUAL_MIC_DEVICE", "BlackHole 2ch"),
        "conversation_sink1_name": os.environ.get("VIRTUAL_SINK1_DEVICE", "BlackHole 2ch"),
        "conversation_sink2_name": os.environ.get("VIRTUAL_SINK2_DEVICE", "BlackHole 16ch"),
        "conversation_mic1_name": os.environ.get("VIRTUAL_MIC1_DEVICE", "BlackHole 2ch"),
        "conversation_mic2_name": os.environ.get("VIRTUAL_MIC2_DEVICE", "BlackHole 16ch"),
    })
else:
    DEFAULTS.update({
        "virtual_sink_name": "VirtualSink",
        "virtual_mic_name": "VirtualMic",
        "conversation_sink1_name": "VirtualSink1",
        "conversation_sink2_name": "VirtualSink2",
        "conversation_mic1_name": "VirtualMic1",
        "conversation_mic2_name": "VirtualMic2",
    })

# Fields the user is not allowed to set to empty / wrong type
_VALIDATORS = {
    "default_volume": lambda v: isinstance(v, int) and 0 <= v <= 500,
    "sample_rate": lambda v: isinstance(v, int) and v > 0,
    "channels": lambda v: isinstance(v, int) and v in (1, 2),
    "conversation_gap_min": lambda v: isinstance(v, (int, float)) and v >= 0,
    "conversation_gap_max": lambda v: isinstance(v, (int, float)) and v >= 0,
    "allowed_speeds": lambda v: isinstance(v, list) and len(v) > 0 and all(isinstance(s, (int, float)) and s > 0 for s in v),
    "port": lambda v: isinstance(v, int) and 1 <= v <= 65535,
    "tts_provider": lambda v: isinstance(v, str) and v in ("elevenlabs", "deepgram"),
}


class Config:
    def __init__(self):
        self._data = dict(DEFAULTS)
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH) as f:
                    saved = json.load(f)
                self._data.update(saved)
            except (json.JSONDecodeError, OSError):
                pass

    def save(self):
        with open(CONFIG_PATH, "w") as f:
            json.dump(self._data, f, indent=2)

    def __getitem__(self, key):
        return self._data[key]

    def to_dict(self):
        return dict(self._data)

    def update(self, changes: dict) -> list[str]:
        """Apply *changes*, save, and return a list of validation errors (if any)."""
        errors = []
        accepted = {}
        for k, v in changes.items():
            if k not in DEFAULTS:
                continue
            validator = _VALIDATORS.get(k)
            if validator and not validator(v):
                errors.append(f"Invalid value for {k}")
            else:
                accepted[k] = v
        if not errors:
            self._data.update(accepted)
            self.save()
        return errors

    def conversation_sink_name(self, speaker: int) -> str:
        return self._data[f"conversation_sink{speaker}_name"]

    def conversation_mic_name(self, speaker: int) -> str:
        return self._data[f"conversation_mic{speaker}_name"]


config = Config()
