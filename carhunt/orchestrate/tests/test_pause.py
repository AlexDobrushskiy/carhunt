import pytest

from carhunt.orchestrate import pause


class FakeSender:
    def __init__(self):
        self.sent = []

    def send(self, text):
        pause.guard()
        self.sent.append(text)


def test_pause_blocks_sender_until_unpause(home):
    s = FakeSender()
    s.send("one")
    pause.pause("night", by="schedule")
    with pytest.raises(pause.Paused, match="night"):
        s.send("two")
    assert s.sent == ["one"]
    pause.unpause(by="owner")
    s.send("three")
    assert s.sent == ["one", "three"]


def test_agents_cannot_unpause(home, monkeypatch):
    pause.pause("owner hold")
    monkeypatch.setenv("CARHUNT_AGENT", "outreach")
    with pytest.raises(pause.Paused, match="only the owner"):
        pause.unpause()
    assert pause.paused()
    assert pause.unpause(by="schedule") is True and not pause.paused()
