import os
import subprocess
import sys
import textwrap
import types

from carhunt.core import doctor


def _root(tmp_path, mods: dict) -> types.ModuleType:
    base = tmp_path / "fakeroot"
    for pkg, body in mods.items():
        d = base / pkg
        d.mkdir(parents=True)
        (d / "__init__.py").write_text("")
        if body is not None:
            (d / "doctor.py").write_text(textwrap.dedent(body))
    m = types.ModuleType("fakeroot")
    m.__path__ = [str(base)]
    sys.modules["fakeroot"] = m
    return m


def test_aggregates_and_never_crashes(tmp_path):
    root = _root(tmp_path, {
        "good": """
            from carhunt.core.doctor import Check
            def checks():
                return [Check("thing", "ok", "fine"), Check("other", "warn", "meh", "do x")]
        """,
        "crashy": "def checks():\n    raise RuntimeError('kaput')\n",
        "badimport": "import not_a_module_xyz\n",
        "nochecks": None,
    })
    try:
        res = doctor.run_all(root, expected=("good", "crashy", "badimport", "nochecks", "missing"))
    finally:
        for k in [k for k in sys.modules if k.startswith("fakeroot")]:
            del sys.modules[k]
    by = {c.name: c for c in res}
    assert by["thing"].status == "ok" and by["thing"].module == "good"
    assert by["crashy: checks"].status == "fail" and "kaput" in by["crashy: checks"].detail
    assert by["badimport: checks"].status == "fail"
    assert by["nochecks: checks"].status == "warn"
    assert by["missing: installed"].status == "warn"
    assert doctor.exit_code(res) == 1
    text = doctor.render(res)
    assert "fix: do x" in text and "1 ok, 3 warn, 2 fail" in text


def test_cli_doctor_runs_every_module(example_config, tmp_path):
    """Real tree, nothing running: one line per check, down services warn, every module reports, no crash."""
    env = {**os.environ, "CARDB_URL": "http://127.0.0.1:9"}  # nothing listens: cardb = warn
    r = subprocess.run([sys.executable, "-m", "carhunt", "doctor", "--json"], capture_output=True, text=True, env=env)
    assert "Traceback" not in r.stderr
    import json
    res = json.loads(r.stdout)
    by = {c["name"]: c for c in res}
    assert by["config"]["status"] == "ok" and by["cardb"]["status"] == "warn"
    assert by["web"]["status"] in ("ok", "warn") and by["web"]["detail"].startswith(doctor.WEB_URL)
    assert {c["module"] for c in res} >= set(doctor.EXPECTED)
    crashed = [c for c in res if c["name"].endswith(": checks") and c["status"] == "fail"]
    assert crashed == [], crashed
    assert not any(c["name"].endswith(": installed") for c in res), "all design.md modules are on main"
    r = subprocess.run([sys.executable, "-m", "carhunt", "doctor"], capture_output=True, text=True, env=env)
    assert r.returncode in (0, 1)
    assert all(line.split()[0] in ("ok", "WARN", "FAIL", "fix:") for line in r.stdout.splitlines()[:-2] if line.strip())


def test_cli_doctor_fails_without_config():
    r = subprocess.run([sys.executable, "-m", "carhunt", "doctor", "--json"], capture_output=True, text=True)
    import json
    res = json.loads(r.stdout)
    assert r.returncode == 1
    assert any(c["name"] == "config" and c["status"] == "fail" for c in res)


def test_web_check_ok_and_down():
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/health" else 404)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = types.SimpleNamespace(get=lambda k, d=None: f"http://127.0.0.1:{srv.server_port}" if k == "web.url" else d)
    try:
        assert doctor._web_check(cfg).status == "ok"
    finally:
        srv.shutdown()
        srv.server_close()
    down = doctor._web_check(types.SimpleNamespace(get=lambda k, d=None: "http://127.0.0.1:9" if k == "web.url" else d))
    assert down.status == "warn" and down.detail.startswith("http://127.0.0.1:9/health") and "compose" in down.fix
