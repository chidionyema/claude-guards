

# crew#407: a test must never reach Telegram or any host. Two real messages left this suite on
# 2026-08-27 while a guard was being written; the guard was wrong and the test had a live token.
import socket as _socket
import pytest as _pytest


@_pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def _refuse(*a, **k):
        raise RuntimeError("REFUSED: test opened a network socket (crew#407)")
    monkeypatch.setattr(_socket.socket, "connect", _refuse)
