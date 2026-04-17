# ElevenLabs TTS Conversation Generation — Design Spec

## Overview

A one-shot Python script (`generate_conversation.py`) that reads an existing plain-text transcript, generates MP3 audio for each turn using the ElevenLabs TTS API, and writes a conversation script JSON ready to be loaded by the audio router webapp's conversation mode.

## Input

- **Transcript**: `/home/hamir/Documents/samples/convo`
- Format: plain text, paragraphs separated by blank lines, each paragraph begins with `SpeakerName: text`
- Three speakers: David (financial advisor), Mark (client, husband), Sarah (client, wife)

## Speaker & Voice Mapping

| Speaker | Role | ElevenLabs Voice | Webapp Speaker |
|---------|------|-----------------|----------------|
| David | Financial advisor | Daniel | 1 |
| Mark | Client (husband) | Charlie | 2 |
| Sarah | Client (wife) | Rachel | 2 |

David is Speaker 1 (advisor side); Mark and Sarah are both Speaker 2 (client side — they're in the same room).

## Output

- **Audio files**: `/home/hamir/Documents/samples/conversations/financial-review/turn_NNN_name.mp3`
  - Zero-padded 3-digit index, e.g. `turn_001_david.mp3`
- **JSON script**: `/home/hamir/Documents/samples/conversations/financial-review.json`

### JSON script format

```json
{
  "gap": 1.0,
  "turns": [
    {"speaker": 1, "file": "conversations/financial-review/turn_001_david.mp3"},
    {"speaker": 2, "file": "conversations/financial-review/turn_002_mark.mp3"},
    ...
  ]
}
```

`file` paths are relative to `SAMPLES_DIR` (`/home/hamir/Documents/samples`), matching how the webapp resolves them.

## Script Behaviour

1. Load `ELEVENLABS_API_KEY` from `audiotool/.env`.
2. Parse the transcript into an ordered list of `(speaker_name, text)` tuples.
3. Create the output directory if it doesn't exist.
4. For each turn:
   a. Derive the output filename from index and lowercased speaker name.
   b. If the MP3 already exists, skip the API call (idempotent — safe to re-run).
   c. Call ElevenLabs TTS with the appropriate voice ID, save the MP3.
   d. Print progress: `[3/22] David → turn_003_david.mp3`
5. Write `financial-review.json` with the full turns list.
6. Print a summary: total turns, files generated vs skipped, JSON path.

## Dependencies

- `requests` (already available in the environment) — used for ElevenLabs HTTP API calls directly, avoiding an extra SDK dependency.
- `python-dotenv` — to load `.env`. If not available, fall back to reading the file manually.

## Error Handling

- Missing transcript file → print clear error and exit.
- Missing `ELEVENLABS_API_KEY` → print clear error and exit.
- Non-200 response from ElevenLabs → print error with status/body and exit (don't write partial JSON).
- Unknown speaker name in transcript → print warning and skip the turn.

## Files Changed

- **New**: `generate_conversation.py` (root of audiotool repo)
- **New**: `/home/hamir/Documents/samples/conversations/financial-review/turn_*.mp3` (generated, not in repo)
- **New**: `/home/hamir/Documents/samples/conversations/financial-review.json` (generated, not in repo)
