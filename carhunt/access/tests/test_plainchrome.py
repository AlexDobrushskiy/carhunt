"""plain-chrome: offline parts against a fake DevTools browser; one opt-in real-Chrome smoke (-m chrome)."""
import http.server
import os
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

from carhunt.access import chrome, jar, plainchrome, reaper
from carhunt.access import settings as _settings
from carhunt.access.tests.test_jar import HOUR, make_profile

FAKE = r'''
import json, sys, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote
port = int(next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--remote-debugging-port=")))
url = [a for a in sys.argv[1:] if not a.startswith("--")][-1]
pages = [{"id": uuid.uuid4().hex.upper(), "type": "page", "url": url, "title": url}]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        if self.path == "/json/version": self._send({"Browser": "Fake/1.0"})   # no webSocketDebuggerUrl
        elif self.path == "/json/list": self._send(pages)
        elif self.path.startswith("/json/close/"):
            t = self.path.rsplit("/", 1)[1]; pages[:] = [p for p in pages if p["id"] != t]; self._send("closing")
        else: self.send_error(404)
    def do_PUT(self):
        u = unquote(self.path.split("?", 1)[1]) if "?" in self.path else "about:blank"
        t = {"id": uuid.uuid4().hex.upper(), "type": "page", "url": u, "title": u}; pages.append(t); self._send(t)

ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
'''


@pytest.fixture
def fake_chrome(tmp_path, carhunt_home, monkeypatch):
    exe = tmp_path / "fake-chrome"
    exe.write_text(f"#!{sys.executable}\n{FAKE}")
    exe.chmod(0o755)
    monkeypatch.setenv("CARHUNT_CHROME", str(exe))
    monkeypatch.setenv("CARHUNT_PLAIN_EXEC", "1")
    yield exe
    for inst in plainchrome.instances():  # never leave a fake running
        try:
            os.kill(inst["pid"], signal.SIGKILL)
            os.waitpid(inst["pid"], 0)
        except (ProcessLookupError, ChildProcessError):
            pass


def _gone(pid):
    return not plainchrome._pid_alive(pid)


def test_build_args_person_like(tmp_path):
    a = plainchrome.build_args(tmp_path, 19999)
    assert f"--user-data-dir={tmp_path}" in a and "--remote-debugging-port=19999" in a
    assert "--use-mock-keychain" in a and "--password-store=basic" in a
    assert "--window-position=-3000,0" in a
    assert not any(x.startswith(("--enable-automation", "--headless", "--remote-debugging-pipe")) for x in a)
    assert "--window-position=-3000,0" not in plainchrome.build_args(tmp_path, 1, onscreen=True)
    h = plainchrome.build_args(tmp_path, 1, headless=True)
    assert "--headless=new" in h and "--window-position=-3000,0" not in h


def test_port_for_known_profiles(carhunt_home, tmp_path):
    s = _settings.load()
    assert plainchrome.port_for(s.profiles / "plain") == s.plain_debug_port
    assert plainchrome.port_for(s.profiles / "identity") == s.debug_port("identity")
    assert plainchrome.port_for(s.profiles / "identity-b") == s.debug_port("identity-b")
    assert plainchrome.port_for(s.profiles / "identity-z") is None
    assert plainchrome.port_for(tmp_path / "elsewhere") is None


def test_use_open_only_for_app_bundles_on_macos(monkeypatch, tmp_path):
    exe = tmp_path / "Agent Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    monkeypatch.delenv("CARHUNT_PLAIN_EXEC", raising=False)
    assert plainchrome._use_open(exe, False) == (sys.platform == "darwin")
    assert not plainchrome._use_open(exe, True)
    assert not plainchrome._use_open(tmp_path / "chrome", False)
    monkeypatch.setenv("CARHUNT_PLAIN_EXEC", "1")
    assert not plainchrome._use_open(exe, False)


def test_second_caller_gets_a_tab_and_browser_quits_after_last_holder(fake_chrome, carhunt_home):
    prof = plainchrome.shared_profile()
    make_profile(prof, [(".example.invalid", "datadome", "SYN-dd", HOUR, 0)])  # a solve sitting in the profile
    port1, t1, reused1 = plainchrome.start("http://127.0.0.1:9/a", prof, holder=os.getppid())  # "another agent"
    port2, t2, reused2 = plainchrome.start("http://127.0.0.1:9/b", prof, holder=os.getpid())
    assert (reused1, reused2) == (False, True) and port1 == port2 and t1 != t2
    recs = [r for r in chrome.read_pid_records() if r.kind == "plain"]
    assert len(recs) == 1 and recs[0].debug_port == port1 and recs[0].profile == str(prof)
    pid = recs[0].pid
    assert plainchrome.status()[0]["holders"] == 2
    assert {p.pid: p for p in reaper.scan()}[pid].action == "leave"  # holders alive

    assert plainchrome.release(port2, t2) is True       # other holder left: only the tab closes
    assert not _gone(pid)
    assert plainchrome.release(port1, None) is False    # whole-browser close refused while t1 is held
    assert plainchrome.release(port1, t1) is True       # last holder: quit + jar export
    assert _gone(pid)
    assert plainchrome.instances() == [] and chrome.read_pid_records() == []
    assert jar.get("example.invalid", "datadome") == "SYN-dd"


def test_fresh_profile_is_seeded_then_deleted(fake_chrome, carhunt_home, tmp_path):
    jar.export_from(make_profile(tmp_path / "seed", [(".example.invalid", "_abck", "SYN-ab", HOUR, 0)]))
    prof, temp = plainchrome._profile_for(None, True)
    assert temp and prof.parent == _settings.load().root / "plain-fresh"
    port, target, _ = plainchrome.start("http://127.0.0.1:9/", prof, temp=True, holder=os.getpid())
    assert jar.profile_cookies("example.invalid", prof) == {"_abck": "SYN-ab"}
    assert plainchrome.release(port, target)
    assert not prof.exists()


def test_close_and_cleanup_after_crash(fake_chrome, carhunt_home):
    port, pid = plainchrome.ensure_running()
    assert plainchrome.ensure_running() == (port, pid)   # still one browser
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    assert plainchrome.cleanup_dead() == [port]
    assert plainchrome.instances() == [] and chrome.read_pid_records() == []
    port, pid = plainchrome.ensure_running()
    assert plainchrome.close() is True and _gone(pid)
    assert plainchrome.main(["status"]) == 0


def test_release_unknown_port_touches_nothing(carhunt_home):
    assert plainchrome.release(1) is False


# ---------- real Chrome smoke (opt-in) ----------

PAGE = b"<html><head><title>carhunt smoke</title></head><body>hello from 127.0.0.1</body></html>"


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        if self.path == "/":
            # a bot-check cookie (must reach the jar) and a login-ish one (must not)
            self.send_header("Set-Cookie", "datadome=SYN-smoke-dd; Max-Age=3600; Path=/")
            self.send_header("Set-Cookie", "sessionid=SYN-login; Max-Age=3600; Path=/")
            body = PAGE
        else:  # /echo: show what the browser sent
            body = f"<title>echo</title><pre>{self.headers.get('Cookie', '')}</pre>".encode()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def local_site():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.mark.chrome
@pytest.mark.skipif(os.environ.get("CARHUNT_TEST_CHROME") != "1", reason="real Chrome: set CARHUNT_TEST_CHROME=1")
def test_real_chrome_title_jar_roundtrip(carhunt_home, local_site):
    """Agent Chrome clone (built under the temp CARHUNT_HOME unless CARHUNT_CHROME is set): load, attach, title,
    clean close → datadome in the jar → a --fresh profile is seeded with it."""
    with plainchrome.open_tab(local_site + "/", settle=1.0) as (_browser, page):
        assert page.title() == "carhunt smoke"
        pid = plainchrome.instances()[0]["pid"]
        assert plainchrome.instances()[0]["profile"] == str(plainchrome.shared_profile())
    assert _gone(pid)
    assert jar.get("127.0.0.1", "datadome") == "SYN-smoke-dd"
    assert jar.get("127.0.0.1", "sessionid") is None

    with plainchrome.open_tab(local_site + "/echo", fresh=True, settle=1.0) as (_browser, page):
        fresh = Path(plainchrome.instances()[0]["profile"])
        pid = plainchrome.instances()[0]["pid"]
        sent = page.inner_text("pre")
        assert "datadome=SYN-smoke-dd" in sent and "sessionid" not in sent
    assert _gone(pid) and not fresh.exists()
    time.sleep(0.5)
    assert [p for p in reaper.scan() if p.record] == []
    assert chrome.read_pid_records() == []
