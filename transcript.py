"""Transcript parsing and output file building utilities."""

import re


def parse_transcript(text: str) -> list[dict]:
    """Parse 'Speaker: text' format into structured turns.

    Each line starting with 'Name: ' begins a new turn. Continuation lines
    (not matching the pattern) are appended to the previous turn.

    Returns list of {"speaker": str, "text": str}.
    """
    turns: list[dict] = []
    pattern = re.compile(r"^([A-Za-z][A-Za-z0-9 _-]*):\s+(.+)$")

    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        m = pattern.match(line)
        if m:
            turns.append({"speaker": m.group(1).strip(), "text": m.group(2).strip()})
        elif turns:
            # Continuation of previous turn
            turns[-1]["text"] += " " + line
    return turns


def unique_speakers(turns: list[dict]) -> list[str]:
    """Return unique speaker names in order of first appearance."""
    seen: set[str] = set()
    result: list[str] = []
    for t in turns:
        if t["speaker"] not in seen:
            seen.add(t["speaker"])
            result.append(t["speaker"])
    return result


def auto_speaker_mapping(speakers: list[str]) -> dict[str, int]:
    """Auto-assign first speaker to 1, second to 2. Only works for <= 2 speakers."""
    mapping: dict[str, int] = {}
    for i, name in enumerate(speakers):
        if i < 2:
            mapping[name] = i + 1
        else:
            break
    return mapping


def assign_speaker_numbers(turns: list[dict], mapping: dict[str, int]) -> list[dict]:
    """Add speaker_num to each turn based on the mapping.

    Returns a new list; does not mutate the input.
    Raises ValueError if a speaker is not in the mapping.
    """
    result = []
    for turn in turns:
        speaker = turn["speaker"]
        if speaker not in mapping:
            raise ValueError(f"Speaker '{speaker}' not in mapping")
        result.append({**turn, "speaker_num": mapping[speaker]})
    return result


def build_turns_json(name: str, turns: list[dict], gap_min: float, gap_max: float) -> dict:
    """Build the playback script JSON content.

    Each turn must have speaker_num and speaker fields.
    Returns dict ready to json.dumps.
    """
    return {
        "gap_min": gap_min,
        "gap_max": gap_max,
        "turns": [
            {
                "speaker": t["speaker_num"],
                "file": f"conversations/{name}/{_turn_filename(i, t['speaker'])}",
            }
            for i, t in enumerate(turns, start=1)
        ],
    }


def build_transcript_json(turns: list[dict]) -> dict:
    """Build the transcript.json content with text per turn.

    Each turn must have speaker, speaker_num, and text fields.
    """
    return {
        "turns": [
            {
                "speaker": t["speaker"],
                "speaker_num": t["speaker_num"],
                "file": _turn_filename(i, t["speaker"]),
                "text": t["text"],
            }
            for i, t in enumerate(turns, start=1)
        ],
    }


def _turn_filename(index: int, speaker: str) -> str:
    """Generate turn filename: turn_001_john.mp3"""
    safe_name = re.sub(r"[^a-z0-9]", "_", speaker.lower()).strip("_")
    return f"turn_{index:03d}_{safe_name}.mp3"
