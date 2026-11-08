from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from carhunt.core import clock


@pytest.fixture(autouse=True)
def tz(monkeypatch):
    monkeypatch.setenv("CARHUNT_TZ", "Asia/Tokyo")


def at(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 11, 8, h, m, tzinfo=ZoneInfo("Asia/Tokyo"))


@pytest.mark.parametrize("t, inside", [("09:29", False), ("09:30", True), ("15:00", True), ("21:29", True),
                                       ("21:30", False), ("23:59", False)])
def test_day_window(t, inside):
    assert clock.in_window("09:30-21:30", at(t)) is inside


@pytest.mark.parametrize("t, inside", [("21:29", False), ("21:30", True), ("23:59", True), ("00:00", True),
                                       ("03:00", True), ("09:29", True), ("09:30", False), ("12:00", False)])
def test_window_crossing_midnight(t, inside):
    assert clock.in_window("21:30-09:30", at(t)) is inside


def test_fake_now_is_owner_local(monkeypatch):
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-08T23:15")
    n = clock.now()
    assert (n.hour, n.minute) == (23, 15) and n.utcoffset().total_seconds() == 9 * 3600
    assert clock.in_window("21:30-09:30")
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-08T23:15+00:00")  # aware: converted
    assert clock.now().hour == 8


def test_window_end_and_next_start():
    assert clock.window_end("21:30-09:30", at("23:00")) == datetime(2026, 11, 9, 9, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert clock.window_end("21:30-09:30", at("03:00")) == datetime(2026, 11, 8, 9, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert clock.next_start("09:30-21:30", at("22:00")).day == 9


def test_other_zone_input_converted():
    utc_noon = datetime(2026, 11, 8, 12, 0, tzinfo=ZoneInfo("UTC"))  # 21:00 in Tokyo
    assert clock.in_window("09:30-21:30", utc_noon)


@pytest.mark.parametrize("bad", ["9:30-21:30", "09:30-09:30", "09:30", "24:00-01:00", ""])
def test_bad_windows(bad):
    with pytest.raises(ValueError):
        clock.in_window(bad, at("10:00"))


def test_tz_from_config(monkeypatch, write_config):
    monkeypatch.delenv("CARHUNT_TZ")
    write_config({"owner": {"tz": "America/Denver"}})
    assert str(clock.tz()) == "America/Denver"
