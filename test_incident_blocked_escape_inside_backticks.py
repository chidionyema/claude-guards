"""Incident 2026-08-28 (session f3f21d6e, crew#593): a validated BLOCKED: reply was refused by
idle-guard v2 four times in a row because the reply opened with a markdown backtick, which is the
exact styling the reply-format law shows. The escape existed and could not be reached (LAW 38)."""
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("estate_board", HERE / "estate_board.py")
board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board)

VALID = "BLOCKED: waits founder.\nTried: x\nError: none\nNeed: y\nWho: founder"


def test_plain_blocked_is_an_escape():
    assert board.reply_opens_blocked(VALID) and not board.blocked_missing(VALID)


def test_backticked_blocked_is_the_same_escape():
    assert board.reply_opens_blocked("`" + VALID.replace("BLOCKED:", "BLOCKED:`", 1))
    assert board.reply_opens_blocked("**" + VALID.replace("BLOCKED:", "BLOCKED:**", 1))


def test_blocked_mentioned_later_is_not_an_escape():
    assert not board.reply_opens_blocked("INVENTORY: done. The guard said BLOCKED: earlier.")
