import json
import os
import re
import sys
from pathlib import Path

import httpx

# ── Paths ──────────────────────────────────────────────────────────────────
SAMPLES_DIR     = Path(os.environ.get("SAMPLES_DIR", Path.home() / "Documents" / "samples"))
OUTPUT_NAME     = os.environ.get("CONVERSATION_NAME", "financial-review")
TRANSCRIPT_PATH = Path(os.environ.get("TRANSCRIPT_PATH", SAMPLES_DIR / "convo"))
OUTPUT_DIR      = SAMPLES_DIR / "conversations" / OUTPUT_NAME
SCRIPT_PATH     = SAMPLES_DIR / "conversations" / f"{OUTPUT_NAME}.json"
GAP_MIN         = 0.1
GAP_MAX         = 1.0
SPEECH_SPEED    = 1.2

# ── Name substitutions ─────────────────────────────────────────────────────
NAME_SUBSTITUTIONS = {
    "David": "Amir",
    "Mark":  "Kurt",
}

# ── Voice mapping ──────────────────────────────────────────────────────────
# ElevenLabs voice IDs (stable pre-made voices)
VOICE_IDS = {
    "david": "onwK4e9ZLuTAKqWW03F9",   # Daniel  — professional British male
    "mark":  "IKne3meq5aSn9XLyUdCD",   # Charlie — casual American male
    "sarah": "21m00Tcm4TlvDq8ikWAM",   # Rachel  — American female
}

SPEAKER_NUM = {
    "david": 1,
    "mark":  2,
    "sarah": 2,
}


def parse_transcript(text: str) -> list[tuple[str, str]]:
    """Return list of (speaker_lower, utterance_text) from the transcript.

    Skips everything before [Scene Start]. Only keeps paragraphs that begin
    with David:, Mark:, or Sarah: (case-sensitive, matching the file format).
    """
    turns = []
    in_dialogue = False
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if "[Scene Start]" in para:
            in_dialogue = True
            continue
        if not in_dialogue:
            continue
        m = re.match(r"^(David|Mark|Sarah):\s+(.+)$", para, re.DOTALL)
        if m:
            turns.append((m.group(1).lower(), m.group(2).strip()))
    return turns


def generate_audio(text: str, voice_id: str, api_key: str) -> bytes:
    """Call ElevenLabs TTS and return raw MP3 bytes. Exits on API error."""
    resp = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": "eleven_turbo_v2",
            "speed": SPEECH_SPEED,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=60.0,
    )
    if resp.status_code != 200:
        print(f"ERROR: ElevenLabs {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)
    return resp.content


def _load_api_key() -> str:
    """Read ELEVENLABS_API_KEY from .env next to this script, then os.environ."""
    env_file = Path(__file__).parent / ".env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("ELEVENLABS_API_KEY"):
                _, _, val = line.partition("=")
                return val.strip().strip("'\"")
    return os.environ.get("ELEVENLABS_API_KEY", "")


def main():
    api_key = _load_api_key()
    if not api_key:
        print("ERROR: ELEVENLABS_API_KEY not found in .env or environment", file=sys.stderr)
        sys.exit(1)

    if not TRANSCRIPT_PATH.is_file():
        print(f"ERROR: Transcript not found: {TRANSCRIPT_PATH}", file=sys.stderr)
        sys.exit(1)

    turns = parse_transcript(TRANSCRIPT_PATH.read_text())
    if not turns:
        print("ERROR: No dialogue turns parsed from transcript", file=sys.stderr)
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    script_turns = []
    generated = skipped = 0

    for i, (speaker, text) in enumerate(turns, start=1):
        if speaker not in VOICE_IDS:
            print(f"WARNING: Unknown speaker '{speaker}' at turn {i}, skipping")
            continue

        filename = f"turn_{i:03d}_{speaker}.mp3"
        filepath = OUTPUT_DIR / filename
        rel_path  = f"conversations/{OUTPUT_NAME}/{filename}"

        for old, new in NAME_SUBSTITUTIONS.items():
            text = text.replace(old, new)

        if filepath.exists():
            print(f"[{i}/{len(turns)}] {speaker.title()} → {filename} (skipped)")
            skipped += 1
        else:
            print(f"[{i}/{len(turns)}] {speaker.title()} → {filename} ...")
            filepath.write_bytes(generate_audio(text, VOICE_IDS[speaker], api_key))
            generated += 1

        script_turns.append({"speaker": SPEAKER_NUM[speaker], "file": rel_path})

    SCRIPT_PATH.write_text(json.dumps({"gap_min": GAP_MIN, "gap_max": GAP_MAX, "turns": script_turns}, indent=2))

    print(f"\nDone. {generated} generated, {skipped} skipped.")
    print(f"Script written to: {SCRIPT_PATH}")


if __name__ == "__main__":
    main()
