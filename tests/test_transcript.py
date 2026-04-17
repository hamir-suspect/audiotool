"""Tests for transcript parsing and output building."""

import pytest

from transcript import (
    assign_speaker_numbers,
    auto_speaker_mapping,
    build_transcript_json,
    build_turns_json,
    parse_transcript,
    unique_speakers,
)


def test_parse_basic():
    text = "John: Hello there\nAlice: Hi John"
    turns = parse_transcript(text)
    assert len(turns) == 2
    assert turns[0] == {"speaker": "John", "text": "Hello there"}
    assert turns[1] == {"speaker": "Alice", "text": "Hi John"}


def test_parse_multiline_continuation():
    text = "John: This is a long\nstatement that continues\nAlice: Ok"
    turns = parse_transcript(text)
    assert len(turns) == 2
    assert turns[0]["text"] == "This is a long statement that continues"
    assert turns[1]["text"] == "Ok"


def test_parse_empty():
    assert parse_transcript("") == []
    assert parse_transcript("   \n  \n  ") == []


def test_parse_no_valid_turns():
    assert parse_transcript("just some random text\nwithout speaker format") == []


def test_parse_strips_whitespace():
    text = "  John:   Hello there  \n  Alice:  Hi  "
    turns = parse_transcript(text)
    assert turns[0]["text"] == "Hello there"
    assert turns[1]["text"] == "Hi"


def test_unique_speakers():
    turns = [
        {"speaker": "John", "text": "a"},
        {"speaker": "Alice", "text": "b"},
        {"speaker": "John", "text": "c"},
    ]
    assert unique_speakers(turns) == ["John", "Alice"]


def test_unique_speakers_empty():
    assert unique_speakers([]) == []


def test_auto_speaker_mapping_two():
    assert auto_speaker_mapping(["John", "Alice"]) == {"John": 1, "Alice": 2}


def test_auto_speaker_mapping_one():
    assert auto_speaker_mapping(["John"]) == {"John": 1}


def test_auto_speaker_mapping_three():
    mapping = auto_speaker_mapping(["John", "Alice", "Bob"])
    assert mapping == {"John": 1, "Alice": 2}


def test_assign_speaker_numbers():
    turns = [{"speaker": "John", "text": "hi"}, {"speaker": "Alice", "text": "hey"}]
    mapping = {"John": 1, "Alice": 2}
    result = assign_speaker_numbers(turns, mapping)
    assert result[0]["speaker_num"] == 1
    assert result[1]["speaker_num"] == 2
    # Original not mutated
    assert "speaker_num" not in turns[0]


def test_assign_speaker_numbers_missing():
    turns = [{"speaker": "John", "text": "hi"}]
    with pytest.raises(ValueError, match="John"):
        assign_speaker_numbers(turns, {})


def test_build_turns_json():
    turns = [
        {"speaker": "John", "speaker_num": 1, "text": "hello"},
        {"speaker": "Alice", "speaker_num": 2, "text": "hi"},
    ]
    result = build_turns_json("test-conv", turns, 0.1, 1.0)
    assert result["gap_min"] == 0.1
    assert result["gap_max"] == 1.0
    assert len(result["turns"]) == 2
    assert result["turns"][0]["speaker"] == 1
    assert result["turns"][0]["file"] == "conversations/test-conv/turn_001_john.mp3"
    assert result["turns"][1]["speaker"] == 2
    assert result["turns"][1]["file"] == "conversations/test-conv/turn_002_alice.mp3"


def test_build_transcript_json():
    turns = [
        {"speaker": "John", "speaker_num": 1, "text": "hello"},
        {"speaker": "Alice", "speaker_num": 2, "text": "hi"},
    ]
    result = build_transcript_json(turns)
    assert len(result["turns"]) == 2
    assert result["turns"][0]["speaker"] == "John"
    assert result["turns"][0]["speaker_num"] == 1
    assert result["turns"][0]["file"] == "turn_001_john.mp3"
    assert result["turns"][0]["text"] == "hello"
