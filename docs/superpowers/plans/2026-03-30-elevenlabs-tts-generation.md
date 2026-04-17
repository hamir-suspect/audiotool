# ElevenLabs TTS Conversation Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write `generate_conversation.py` — a one-shot script that parses the financial review transcript, calls ElevenLabs TTS for each turn, and produces MP3 files + a `financial-review.json` conversation script ready for the audio router webapp.

**Architecture:** Single script with two pure helper functions (`parse_transcript`, `generate_audio`) and a `main()` that wires them together. No classes, no config files, no CLI args — just run it. Tests cover the two pure functions; the integration (file I/O + real API) is verified by running the script.

**Tech Stack:** Python 3.11+, `httpx` (already in requirements), `pytest` (already in requirements), ElevenLabs REST API v1.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `generate_conversation.py` | Create | Script entry point + helpers |
| `tests/test_generate_conversation.py` | Create | Unit tests for parser and API call |
| `requirements.txt` | No change | httpx already present |

---

### Task 1: Transcript parser — test first

**Files:**
- Create: `tests/test_generate_conversation.py`
- Create: `generate_conversation.py` (stub + `parse_transcript` only)

- [ ] **Step 1: Write the failing test**

Create `tests/test_generate_conversation.py`:

```python
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generate_conversation as gc

SAMPLE = """Transcript: Test

Participants:

David: Financial Advisor

Mark: Client (Husband)

[Scene Start]

David: Hello there, how are you?

Mark: I am doing well, thank you.

Sarah: Same here, thanks for asking.

David: Great to hear.
"""


def test_parse_returns_correct_speakers():
    turns = gc.parse_transcript(SAMPLE)
    assert [t[0] for t in turns] == ["david", "mark", "sarah", "david"]


def test_parse_returns_correct_text():
    turns = gc.parse_transcript(SAMPLE)
    assert turns[0][1] == "Hello there, how are you?"
    assert turns[1][1] == "I am doing well, thank you."


def test_parse_skips_participant_header():
    turns = gc.parse_transcript(SAMPLE)
    texts = [t[1] for t in turns]
    assert not any("Financial Advisor" in t for t in texts)
    assert not any("Client" in t for t in texts)


def test_parse_skips_before_scene_start():
    # Everything before [Scene Start] must be ignored
    turns = gc.parse_transcript(SAMPLE)
    assert len(turns) == 4


def test_parse_empty_transcript():
    assert gc.parse_transcript("") == []
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool
pytest tests/test_generate_conversation.py -v
```

Expected: `ModuleNotFoundError` or `AttributeError` — `generate_conversation` doesn't exist yet.

- [ ] **Step 3: Create `generate_conversation.py` with `parse_transcript`**

```python
import json
import os
import re
import sys
from pathlib import Path

import httpx

# ── Paths ──────────────────────────────────────────────────────────────────
TRANSCRIPT_PATH = Path("/home/hamir/Documents/samples/convo")
SAMPLES_DIR     = Path("/home/hamir/Documents/samples")
OUTPUT_NAME     = "financial-review"
OUTPUT_DIR      = SAMPLES_DIR / "conversations" / OUTPUT_NAME
SCRIPT_PATH     = SAMPLES_DIR / "conversations" / f"{OUTPUT_NAME}.json"
GAP             = 1.0

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

        if filepath.exists():
            print(f"[{i}/{len(turns)}] {speaker.title()} → {filename} (skipped)")
            skipped += 1
        else:
            print(f"[{i}/{len(turns)}] {speaker.title()} → {filename} ...")
            filepath.write_bytes(generate_audio(text, VOICE_IDS[speaker], api_key))
            generated += 1

        script_turns.append({"speaker": SPEAKER_NUM[speaker], "file": rel_path})

    SCRIPT_PATH.write_text(json.dumps({"gap": GAP, "turns": script_turns}, indent=2))

    print(f"\nDone. {generated} generated, {skipped} skipped.")
    print(f"Script written to: {SCRIPT_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run parser tests — verify they pass**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool
pytest tests/test_generate_conversation.py::test_parse_returns_correct_speakers \
       tests/test_generate_conversation.py::test_parse_returns_correct_text \
       tests/test_generate_conversation.py::test_parse_skips_participant_header \
       tests/test_generate_conversation.py::test_parse_skips_before_scene_start \
       tests/test_generate_conversation.py::test_parse_empty_transcript \
       -v
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add generate_conversation.py tests/test_generate_conversation.py
git commit -m "feat: add transcript parser for TTS generation script"
```

---

### Task 2: ElevenLabs API function — test first

**Files:**
- Modify: `tests/test_generate_conversation.py` (append new tests)

- [ ] **Step 1: Append API tests to the test file**

Add to the bottom of `tests/test_generate_conversation.py` (imports are already at the top from Task 1):

```python
def test_generate_audio_returns_mp3_bytes():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"fake-mp3-bytes"

    with patch("generate_conversation.httpx.post", return_value=mock_resp):
        result = gc.generate_audio("Hello world", "voice123", "apikey456")

    assert result == b"fake-mp3-bytes"


def test_generate_audio_sends_correct_voice_id():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"audio"

    with patch("generate_conversation.httpx.post", return_value=mock_resp) as mock_post:
        gc.generate_audio("Hello", "my-voice-id", "my-key")

    url = mock_post.call_args[0][0]
    assert "my-voice-id" in url


def test_generate_audio_sends_api_key_header():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"audio"

    with patch("generate_conversation.httpx.post", return_value=mock_resp) as mock_post:
        gc.generate_audio("Hello", "voice", "secret-key")

    headers = mock_post.call_args[1]["headers"]
    assert headers["xi-api-key"] == "secret-key"


def test_generate_audio_exits_on_401():
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"

    with patch("generate_conversation.httpx.post", return_value=mock_resp):
        with pytest.raises(SystemExit):
            gc.generate_audio("Hello", "bad-voice", "bad-key")
```

- [ ] **Step 2: Run new tests — verify they pass**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool
pytest tests/test_generate_conversation.py -v
```

Expected: all 9 tests pass (5 parser + 4 API).

- [ ] **Step 3: Commit**

```bash
git add tests/test_generate_conversation.py
git commit -m "feat: add ElevenLabs API function tests"
```

---

### Task 3: Run the script — generate audio files and JSON

This task hits the real ElevenLabs API. No code changes needed — `generate_conversation.py` is already complete.

- [ ] **Step 1: Dry-run parse check**

Verify the transcript parses into the expected number of turns:

```bash
cd /home/hamir/Documents/dsoignoo/audiotool
python3 -c "
import generate_conversation as gc
from pathlib import Path
turns = gc.parse_transcript(Path('/home/hamir/Documents/samples/convo').read_text())
print(f'{len(turns)} turns found')
for i, (spk, txt) in enumerate(turns, 1):
    print(f'  [{i}] {spk}: {txt[:60]}...' if len(txt) > 60 else f'  [{i}] {spk}: {txt}')
"
```

Expected: ~27 turns, speakers alternating between david/mark/sarah. Confirm nothing looks garbled before spending API credits.

- [ ] **Step 2: Run the generation script**

```bash
cd /home/hamir/Documents/dsoignoo/audiotool
python3 generate_conversation.py
```

Expected output (one line per turn, then summary):
```
[1/27] David → turn_001_david.mp3 ...
[2/27] David → turn_002_david.mp3 ...
...
Done. 27 generated, 0 skipped.
Script written to: /home/hamir/Documents/samples/conversations/financial-review.json
```

- [ ] **Step 3: Verify output files exist**

```bash
ls /home/hamir/Documents/samples/conversations/financial-review/ | head -10
ls /home/hamir/Documents/samples/conversations/financial-review/ | wc -l
cat /home/hamir/Documents/samples/conversations/financial-review.json | head -20
```

Expected: N `.mp3` files, JSON with correct `turns` array, `speaker` values are 1 or 2, `file` paths start with `conversations/financial-review/`.

- [ ] **Step 4: Verify JSON is valid for the webapp**

```bash
python3 -c "
import json
from pathlib import Path
data = json.loads(Path('/home/hamir/Documents/samples/conversations/financial-review.json').read_text())
turns = data['turns']
print(f'gap: {data[\"gap\"]}')
print(f'turns: {len(turns)}')
assert all(t['speaker'] in (1, 2) for t in turns), 'bad speaker'
assert all(Path('/home/hamir/Documents/samples/' + t['file']).is_file() for t in turns), 'missing file'
print('All files exist. JSON is valid.')
"
```

Expected: `All files exist. JSON is valid.`

- [ ] **Step 5: Commit**

```bash
git add generate_conversation.py
git commit -m "feat: add ElevenLabs TTS generation script for financial-review conversation"
```
