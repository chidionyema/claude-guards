#!/usr/bin/env python3
"""The Kimi answer parser, against a real recorded stream.

fixtures/kimi-connect-stream.bin is a byte-for-byte capture of one
kimi.gateway.chat.v1.ChatService/Chat response, recorded 2026-08-22 from the
question "Name three fruits, one per line, nothing else." It is the oracle: the
parser is right when it returns what that stream actually said.

Three separate things in the stream are not the answer, and each one is its own
assertion here because each has a different way of leaking into a reply:
reasoning, the model-degrade banner, and stage or status frames.

Run: python3 test_kimi_connect_parser.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import kimi_bridge as kb

RAW = (HERE / "fixtures" / "kimi-connect-stream.bin").read_bytes()


def test_frames_walk_the_whole_body():
    frames = list(kb.connect_frames(RAW))
    assert len(frames) == 59, f"expected 59 frames, got {len(frames)}"
    assert frames[0][1] == b'{"heartbeat":{}}', frames[0][1]
    print(f"PASS  walked {len(frames)} frames, first is the heartbeat")


def test_the_answer_is_exactly_what_kimi_said():
    got = kb.connect_stream_text(RAW)
    assert got == "Apple\nBanana\nOrange", repr(got)
    print(f"PASS  answer is {got!r}")


def test_reasoning_never_reaches_the_answer():
    got = kb.connect_stream_text(RAW)
    # 35 of the 59 frames are block.think.content. If the mask filter is ever
    # loosened, this is the phrase that shows up glued to the front.
    for leak in ("should just list", "user wants", "no extra text"):
        assert leak not in got, f"reasoning leaked: {leak!r} in {got!r}"
    print("PASS  none of the 35 reasoning frames reached the answer")


def test_the_degrade_banner_never_reaches_the_answer():
    got = kb.connect_stream_text(RAW)
    assert "High demand" not in got, got
    assert "K2.6" not in got, got
    print("PASS  the model-degrade banner stayed out of the answer")


def test_a_truncated_stream_returns_what_it_read():
    """A cut-off stream is common: the browser closes, the network drops. The
    words already decoded are still worth returning, so this must not raise."""
    half = kb.connect_stream_text(RAW[: len(RAW) // 2])
    assert isinstance(half, str)
    assert "Apple" not in half, "the fixture's answer starts past the halfway mark"
    print(f"PASS  a truncated stream returned {half!r} instead of raising")


def test_junk_is_not_mistaken_for_a_stream():
    assert kb.connect_stream_text(b"") == ""
    assert kb.connect_stream_text(b'{"choices":[]}') == ""
    print("PASS  a non-Connect body yields nothing rather than garbage")


if __name__ == "__main__":
    test_frames_walk_the_whole_body()
    test_the_answer_is_exactly_what_kimi_said()
    test_reasoning_never_reaches_the_answer()
    test_the_degrade_banner_never_reaches_the_answer()
    test_a_truncated_stream_returns_what_it_read()
    test_junk_is_not_mistaken_for_a_stream()
    print("\n6/6 green")
