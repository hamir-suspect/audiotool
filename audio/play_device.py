"""Stdin-to-sounddevice bridge — replaces paplay on Windows.

Usage:
    ffmpeg ... -f s16le -ac 2 -ar 48000 - | python play_device.py --device "CABLE Input"
"""

import argparse
import sys

import sounddevice as sd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", required=True, help="Output device name")
    parser.add_argument("--samplerate", type=int, default=48000)
    parser.add_argument("--channels", type=int, default=2)
    args = parser.parse_args()

    bytes_per_sample = 2  # 16-bit PCM
    block_frames = args.samplerate  # 1 second of audio per block
    block_bytes = block_frames * args.channels * bytes_per_sample

    stream = sd.RawOutputStream(
        samplerate=args.samplerate,
        channels=args.channels,
        dtype="int16",
        device=args.device,
    )
    stream.start()
    try:
        while True:
            data = sys.stdin.buffer.read(block_bytes)
            if not data:
                break
            stream.write(data)
    finally:
        stream.stop()
        stream.close()


if __name__ == "__main__":
    main()
