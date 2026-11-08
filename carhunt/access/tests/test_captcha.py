"""Captcha solver: offline tests on synthetic fixtures (no real captcha images, no network, no Ollama)."""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from carhunt.access.captcha import core, grid, inputs, slider, vision
from carhunt.access.captcha.attempts import AttemptLog
from carhunt.access.captcha.config import CaptchaConfig
from carhunt.access.captcha.detect import classify
from carhunt.access.captcha.static import StaticPage, parse, select
from carhunt.access.captcha.vlm import Ollama

REPO = Path(__file__).resolve().parents[3]
FIX = Path(__file__).parent / "fixtures" / "captcha"
_spec = importlib.util.spec_from_file_location("make_fixtures", FIX / "make_fixtures.py")
mf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mf)


@pytest.fixture
def no_sleep(monkeypatch):
    for mod in (core, slider, inputs):
        monkeypatch.setattr(mod.time, "sleep", lambda s: None)


def enabled(**kw) -> CaptchaConfig:
    return CaptchaConfig(enabled=True, screenshots=False, **kw)


# ---------------------------------------------------------------- puzzle / slider maths

@pytest.mark.parametrize("seed", range(6))
def test_gap_found_from_puzzle_images(seed):
    bg, piece, gx, py = mf.puzzle(np.random.default_rng(seed))
    g, px, gy = vision.gap_from_images(bg, piece)
    assert abs(g.x - gx) <= 3
    assert gy == py and px == mf.PIECE_X + 1


def test_gap_from_png_roundtrip(tmp_path):
    """Same as the image path the solver uses: canvas PNG data URLs decoded with alpha."""
    bg, piece, gx, _ = mf.puzzle(np.random.default_rng(42))
    url = "data:image/png;base64," + base64.b64encode(cv2.imencode(".png", piece)[1].tobytes()).decode()
    dec = vision.decode_data_url(url)
    assert dec.shape[2] == 4
    g, _, _ = vision.gap_from_images(bg, dec)
    assert abs(g.x - gx) <= 3


def test_piece_shape_and_gap_from_probe_motion():
    """No readable pixels: the piece shape comes from what moved between two screenshots."""
    bg, piece, gx, py = mf.puzzle(np.random.default_rng(3))
    A, B = mf.composite(bg, piece, 0), mf.composite(bg, piece, 30)
    s = slider.Slider(page=None, mouse=None, parts=None)
    m = s._model_from_motion(A, B)
    assert m is not None, s.r.notes
    assert m["shift"] == 30
    assert abs((m["x"] + m["target_S"]) - gx) <= 4


class _Widget:
    """A fake puzzle slider: handle follows the pressed mouse, the piece moves ratio x handle distance."""

    BG = dict(x=50.0, y=100.0, width=320.0, height=160.0)

    def __init__(self, seed: int, ratio: float):
        self.bg, self.piece, self.gx, _ = mf.puzzle(np.random.default_rng(seed))
        self.ratio = ratio
        self.handle_dx = 0.0
        self.pressed = False
        self.grab = None
        self.mx = self.my = 0.0

    @property
    def offset(self) -> float:
        return self.handle_dx * self.ratio

    def box(self, sel):
        if sel == "#bg":
            return dict(self.BG)
        if sel == "#piece":
            return dict(self.BG, x=self.BG["x"] + self.offset)
        if sel == "#handle":
            return dict(x=50.0 + self.handle_dx, y=270.0, width=40.0, height=30.0)
        return None

    def image(self, sel):
        img = self.bg if sel == "#bg" else self.piece
        return {"kind": "canvas", "w": img.shape[1], "h": img.shape[0],
                "data": "data:image/png;base64," + base64.b64encode(cv2.imencode(".png", img)[1].tobytes()).decode()}

    def render(self) -> np.ndarray:
        page = np.full((600, 800, 3), 255, np.uint8)
        b = self.BG
        page[int(b["y"]):int(b["y"] + b["height"]), int(b["x"]):int(b["x"] + b["width"])] = \
            mf.composite(self.bg, self.piece, self.offset)
        return page

    def move(self, x, y):
        self.mx, self.my = x, y
        if self.pressed:
            self.handle_dx = min(max(0.0, x - self.grab), 280.0)


class _Loc:
    def __init__(self, w, sel):
        self.w, self.sel = w, sel
        self.first = self

    def count(self):
        return int(self.w.box(self.sel) is not None)

    def bounding_box(self, timeout=None):
        return self.w.box(self.sel)

    def evaluate(self, js, arg=None):
        return self.w.image(self.sel)

    def is_visible(self):
        return self.count() == 1


class _Frame:
    url = "https://example.invalid/"

    def __init__(self, w):
        self.w = w

    def locator(self, sel):
        return _Loc(self.w, sel)


class _Page:
    viewport_size = {"width": 800, "height": 600}

    def __init__(self, w):
        self.w = w

    def screenshot(self, clip=None, scale="device", **kw):
        img = self.w.render()
        if clip:
            x, y = int(round(clip["x"])), int(round(clip["y"]))
            img = img[y:y + int(round(clip["height"])), x:x + int(round(clip["width"]))]
        return cv2.imencode(".png", img)[1].tobytes()


class _Mouse(inputs.Mouse):
    name = "fake"

    def __init__(self, page, w):
        self.w = w
        super().__init__(page)

    def _move(self, x, y):
        self.w.move(x, y)

    def _down(self):
        self.w.pressed, self.w.grab = True, self.w.mx - self.w.handle_dx

    def _up(self):
        self.w.pressed = False


@pytest.mark.parametrize("seed,ratio", [(1, 1.0), (2, 0.8), (5, 1.25)])
def test_slider_closed_loop_lands_piece_on_gap(no_sleep, seed, ratio):
    """Whole slider engine against a simulated widget: image model, probe pull, ratio, drag, nudge."""
    w = _Widget(seed, ratio)
    page = _Page(w)
    parts = slider.Parts(_Frame(w), "#handle", "#bg", "#piece")
    rep = slider.Slider(page, _Mouse(page, w), parts).run()
    want = w.gx - (mf.PIECE_X + 1)                 # CSS px the piece must travel
    assert rep.method == "canvas"
    assert abs(rep.target_px - want) <= 3
    assert abs(rep.ratio - ratio) < 0.1
    assert abs(w.offset - want) <= 3, rep
    assert not w.pressed


# ---------------------------------------------------------------- grids

@pytest.mark.parametrize("rows,cols", [(3, 3), (4, 4)])
def test_grid_split_matches_tiles(rows, cols):
    img, colours = mf.grid_image(np.random.default_rng(rows), rows, cols)
    tiles = grid.split(img, rows, cols)
    assert len(tiles) == rows * cols
    for t, c in zip(tiles, colours):
        assert t.shape[:2] == (100, 100)
        assert np.abs(t.reshape(-1, 3).mean(0) - c).max() < 1


def test_grid_split_uneven_size_covers_every_pixel():
    img = np.arange(301 * 299, dtype=np.int64).reshape(301, 299)
    tiles = grid.split(img, 4, 4)
    assert sum(t.size for t in tiles) == img.size
    assert np.array_equal(np.sort(np.concatenate([t.ravel() for t in tiles])), img.ravel())


def test_tiles_from_boxes_and_numbered():
    # box over the top-left 1.5 tiles of a 400x400 4x4 grid
    assert grid.tiles_from_boxes([(0, 0, 150, 90, 0.9)], 400, 400, 4, 4) == {0, 1}
    assert grid.tiles_from_boxes([], 400, 400, 4, 4) == set()
    img, _ = mf.grid_image(np.random.default_rng(0), 3, 3)
    assert grid.numbered(img, 3, 3).shape == img.shape


def test_target_of_instruction():
    assert grid.target_of("Select all images with\nbuses\nClick verify once there are none left.") == "buses"
    assert grid.target_of("Select all images with a\nfire hydrant\nClick verify") == "a fire hydrant"
    assert grid.target_of("Select all squares with\ntraffic lights\nIf there are none, click skip") == "traffic lights"
    assert grid.queries("crosswalks")[0].startswith("a pedestrian crosswalk")
    assert grid.queries("boats") == ["a boat"]


# ---------------------------------------------------------------- VLM through a fake Ollama

def fake_ollama(models=("qwen3.5:4b",), calls=None):
    """Transport that sees the image: says "yes" for red-dominant tiles; boxes in Qwen 0..1000 coords."""
    def transport(url, body, timeout):
        if calls is not None:
            calls.append((url, body and body.get("prompt")))
        if url.endswith("/api/tags"):
            if models is None:
                raise OSError("connection refused")
            return {"models": [{"name": m} for m in models]}
        img = cv2.imdecode(np.frombuffer(base64.b64decode(body["images"][0]), np.uint8), cv2.IMREAD_COLOR)
        p = body["prompt"]
        if p.startswith("Does this photo show"):
            b, g, r = img.reshape(-1, 3).mean(0)
            return {"response": "Yes." if r > 150 and r > b + 60 and r > g + 60 else "No"}
        if p.startswith("Locate"):
            return {"response": '[{"bbox_2d": [100, 200, 300, 400], "label": "x"}]'}
        if "CAPTCHA or bot check" in p:
            return {"response": 'Sure: {"captcha": true, "type": "checkbox", "instruction": "I am human"}'}
        return {"response": "[[500, 500]]"}
    return transport


def test_ollama_availability_and_parsing():
    assert Ollama(transport=fake_ollama()).available()
    assert not Ollama(model="qwen3.5:9b", transport=fake_ollama()).available()
    assert not Ollama(transport=fake_ollama(models=None)).available()
    assert Ollama(model="llava", transport=fake_ollama(models=("llava:latest",))).available()
    c = Ollama(transport=fake_ollama())
    img = np.zeros((200, 400, 3), np.uint8)
    assert c.locate(img, "the checkbox") == pytest.approx((40.0, 40.0, 120.0, 80.0))  # 0..1000 -> px
    assert c.classify(img)["type"] == "checkbox"
    assert c.points(img, "click") == [pytest.approx((200.0, 100.0))]


def test_grid_choose_with_fake_vlm():
    rows = cols = 3
    tiles, red = [], {1, 4, 8}
    for i in range(9):
        t = np.full((100, 100, 3), (200, 160, 40), np.uint8)
        if i in red:
            t[:] = (30, 30, 220)
        tiles.append(t)
    table = np.vstack([np.hstack(tiles[r * 3:(r + 1) * 3]) for r in range(3)])
    calls = []
    got = grid.choose(tiles, table, rows, cols, "a fire truck", vlm=Ollama(transport=fake_ollama(calls=calls)))
    assert got == red
    assert len(calls) == 9 and all("a fire truck" in p for _, p in calls)
    notes = []
    grid.choose(tiles[:4] * 4, table, 4, 4, "x", vlm=Ollama(transport=fake_ollama()), notes=notes)
    assert "not benchmarked" in notes[0]
    with pytest.raises(grid.NoClassifier):
        grid.choose(tiles, table, rows, cols, "x", vlm=None)


def test_recaptcha_grid_without_models_is_unsupported():
    ctx = core.Ctx(page=None, mouse=None, shots=None, cfg=enabled(), vlm=None, owl=False)
    assert core._challenge(ctx, "recaptcha", None, None)["outcome"] == "unsupported"
    assert core._challenge(ctx, "hcaptcha", None, None)["outcome"] == "unsupported"


# ---------------------------------------------------------------- detection on synthetic HTML

@pytest.mark.parametrize("name", sorted(mf.WALLS))
def test_detect_wall_kinds(name):
    html, url, frames, kind, status = mf.WALLS[name]
    info = classify(StaticPage(html, url, frames, status).static_snapshot())
    assert (info.kind if info else None) == kind


def test_detect_recaptcha_stages():
    def stage(name):
        html, url, frames, _, status = mf.WALLS[name]
        return classify(StaticPage(html, url, frames, status).static_snapshot()).detail.get("stage")
    assert stage("recaptcha-checkbox") == "checkbox"
    assert stage("recaptcha-grid") == "image-challenge"
    assert stage("recaptcha-grid-hidden") == "checkbox"   # bframe laid out but hidden: not a challenge yet
    assert stage("hcaptcha-challenge") == "image-challenge"


def test_static_selector_subset():
    root = parse('<div class="a slider-x"><span class="b-handle" id="h">x</span></div><p class="b-handle"></p>')
    assert [n.attrs["id"] for n in select(root, "[class*=slider] [class*=handle]")] == ["h"]
    assert len(select(root, ".b-handle")) == 2
    assert len(select(root, "div.a, #h, p")) == 3
    assert select(root, "[class^=slider]") == []


# ---------------------------------------------------------------- solve(): budget, route, attempts

def _geetest_page():
    html, url, frames, _, status = mf.WALLS["geetest"]
    return StaticPage(html, url, frames, status)


@pytest.fixture
def fake_attempts(monkeypatch, no_sleep):
    """The geetest handler does nothing and the wall stays: counts handler calls."""
    calls = []

    def handler(ctx, info, shots):
        calls.append(info.kind)
        return {"method": "fake"}
    monkeypatch.setitem(core.HANDLERS, "geetest-slide", handler)
    monkeypatch.setattr(core, "wait_outcome", lambda page, info, timeout=15: ("failed", info))
    monkeypatch.setattr(core.inputs, "make", lambda page, kind="cdp", port=None: object())
    return calls


def test_budget_two_per_run_six_per_site_window(carhunt_home, monkeypatch, fake_attempts):
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-08T10:00:00+00:00")
    log = AttemptLog()
    assert log.path == carhunt_home / "access" / "captcha.sqlite"
    for run in range(3):
        r = core.solve(_geetest_page(), cfg=enabled(), log=log, use_vlm=False)
        assert (r.status, r.attempts) == ("failed", 2)
    assert len(fake_attempts) == 6
    r = core.solve(_geetest_page(), cfg=enabled(), log=log, use_vlm=False)
    assert r.status == "budget" and len(fake_attempts) == 6
    assert core.solve(_geetest_page(), cfg=enabled(), log=log, use_vlm=False, force=True).status == "failed"
    assert len(fake_attempts) == 8
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-08T15:59:00+00:00")   # 8 attempts still inside 6 h
    assert core.solve(_geetest_page(), cfg=enabled(), log=log, dry_run=True).status == "budget"
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-08T16:00:01+00:00")   # window passed
    assert core.solve(_geetest_page(), cfg=enabled(), log=log, dry_run=True).status == "dry-run"
    assert log.budget_left("example.invalid", 6, 6) == 6
    assert core.solve(_geetest_page(), cfg=enabled(max_attempts=1), log=log, use_vlm=False).attempts == 1


def test_datadome_refused_in_playwright_lanes(carhunt_home, no_sleep):
    html, url, frames, _, status = mf.WALLS["datadome-slider"]
    for route in ("lane", "identity", "identity-b"):
        r = core.solve(StaticPage(html, url, frames, status), route=route, cfg=enabled(), dry_run=True)
        assert r.status == "wrong-route" and "plain-chrome" in r.message
    assert core.solve(StaticPage(html, url, frames, status), route="plain", cfg=enabled(), dry_run=True).status == "dry-run"
    assert core.solve(StaticPage(html, url, frames, status), route="lane", cfg=enabled(), dry_run=True,
                      force=True).status == "dry-run"


def test_solve_statuses_without_action(carhunt_home, no_sleep):
    def page(name):
        html, url, frames, _, status = mf.WALLS[name]
        return StaticPage(html, url, frames, status)
    assert core.solve(page("normal-page"), cfg=enabled()).status == "no-captcha"
    assert core.solve(page("geetest"), cfg=CaptchaConfig()).status == "disabled"   # default: off
    r = core.solve(page("datadome-blocked"), cfg=enabled())
    assert r.status == "hard-block" and r.attempts == 0
    assert core.solve(page("hcaptcha-challenge"), cfg=enabled()).status == "unsupported"
    assert core.site_of("https://www.example.co.uk/x") == "example.co.uk"


def test_config_from_yaml(carhunt_home):
    (carhunt_home / "config.yaml").write_text(
        "browsers:\n  captcha: {enabled: true, model: 'qwen3.5:9b', owlv2: true, ollama_url: 'http://10.0.0.5:11434'}\n")
    from carhunt.access.captcha.config import load
    c = load()
    assert (c.enabled, c.model, c.owlv2, c.ollama_url, c.max_attempts, c.site_budget) == \
        (True, "qwen3.5:9b", True, "http://10.0.0.5:11434", 2, 6)


# ---------------------------------------------------------------- doctor

def test_doctor_warns_never_fails(carhunt_home):
    from carhunt.access.captcha.doctor import checks
    off = checks(CaptchaConfig(), transport=fake_ollama(models=None))
    by = {c["name"]: c for c in off}
    assert {c["status"] for c in off} <= {"ok", "warn"}
    assert by["captcha.enabled"]["status"] == "warn"
    assert by["captcha.ollama"]["status"] == "warn" and "ollama pull" in by["captcha.ollama"]["fix"]
    nomodel = {c["name"]: c for c in checks(enabled(), transport=fake_ollama(models=("llava:latest",)))}
    assert nomodel["captcha.ollama"]["status"] == "warn" and "not pulled" in nomodel["captcha.ollama"]["detail"]
    on = {c["name"]: c for c in checks(enabled(), transport=fake_ollama())}
    assert on["captcha.ollama"]["status"] == "ok"
    assert "recaptcha-grid" in on["captcha.features"]["detail"]
    assert all(set(c) == {"name", "status", "detail", "fix"} for c in on.values())


# ---------------------------------------------------------------- CLI + wrapper

@pytest.fixture
def fixtures_dir(tmp_path):
    d = tmp_path / "fx"
    mf.generate(d, n_puzzles=6, seed=9)
    return d


def test_cli_bench_detect(fixtures_dir, carhunt_home, capsys):
    from carhunt.access.captcha.cli import main
    assert main(["bench", "--fixtures", str(fixtures_dir)]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["puzzles"] == {"ok": 6, "n": 6, "errors_px": r["puzzles"]["errors_px"]}
    assert r["grids"]["ok"] == 2 and r["walls"]["ok"] == r["walls"]["n"] == len(mf.WALLS)

    lab = json.loads((fixtures_dir / "labels.json").read_text())
    p = lab["puzzles"][0]
    assert main(["detect", "--image", str(fixtures_dir / p["bg"]), "--piece", str(fixtures_dir / p["piece"])]) == 0
    out = json.loads(capsys.readouterr().out)
    assert abs(out["gap_x"] - p["gap_x"]) <= 3

    w = next(w for w in lab["walls"] if w["name"] == "datadome-slider")
    frame_args = [a for src, f in w["frames"].items() for a in ("--frame", f"{src}={fixtures_dir / f}")]
    assert main(["detect", "--html", str(fixtures_dir / w["html"]), "--status", "403", *frame_args]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "datadome-slider"


def test_register_adds_captcha_group():
    import argparse

    from carhunt.access.captcha.cli import cmd_solve, register
    ap = argparse.ArgumentParser(prog="carhunt")
    register(ap.add_subparsers(dest="group"))
    a = ap.parse_args(["captcha", "solve", "--identity-b", "--url", "example", "--dry-run"])
    assert (a.route, a.url, a.dry_run, a.func) == ("identity-b", "example", True, cmd_solve)
    with pytest.raises(SystemExit):
        ap.parse_args(["captcha", "solve", "--lane", "--plain"])   # one route only


def test_route_ports_from_settings(carhunt_home):
    import argparse

    from carhunt.access import settings
    from carhunt.access.captcha.cli import _endpoint
    s = settings.load()
    ns = lambda **kw: argparse.Namespace(**{"cdp": None, "route": None, **kw})  # noqa: E731
    assert _endpoint(ns(route="plain")) == (f"http://127.0.0.1:{s.plain_debug_port}", s.plain_debug_port, "plain")
    assert _endpoint(ns(route="lanes"))[1:] == (s.debug_port("lanes"), "lane")
    assert _endpoint(ns(route="identity-a"))[1:] == (s.debug_port("identity-a"), "identity-a")
    assert _endpoint(ns(cdp="http://127.0.0.1:9999"))[1:] == (9999, "cdp")


def test_wrapper_script(fixtures_dir, carhunt_home):
    env = {**os.environ, "CARHUNT_PYTHON": sys.executable}
    w = REPO / "browsers" / "bin" / "captcha-solve"
    r = subprocess.run([str(w), "bench", "--fixtures", str(fixtures_dir)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["walls"]["wrong"] == []
    r = subprocess.run([str(w), "slide-js"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "async (page)" in r.stdout


# ---------------------------------------------------------------- real browser, local page (smoke)

_PAGE = """<html><head><title>Login</title><style>
 body{margin:0;font:14px sans-serif} #w{position:absolute;left:40px;top:60px}
 canvas{position:absolute;left:0;top:0} .slider-track{position:absolute;left:0;top:175px;width:320px;height:36px;background:#ddd}
 .slider-handle{position:absolute;left:0;top:0;width:40px;height:36px;background:#48f;cursor:pointer}
</style></head><body><p>Security captcha: slide to complete the puzzle</p><div id="w">
<canvas id="cap-bg" width="320" height="160"></canvas><canvas class="puzzle-piece" width="320" height="160"></canvas>
<div class="slider-track"><div class="slider-handle"></div></div></div>
<script>
const RATIO = %(ratio)s, TARGET = %(target)s;
const bg = document.getElementById('cap-bg'), pc = document.querySelector('.puzzle-piece'), h = document.querySelector('.slider-handle');
const load = (cv, src) => new Promise(r => { const i = new Image(); i.onload = () => { cv.getContext('2d').drawImage(i, 0, 0); r(); }; i.src = src; });
Promise.all([load(bg, '%(bg)s'), load(pc, '%(piece)s')]).then(() => window.ready = true);
let down = null, dx = 0;
h.addEventListener('mousedown', e => { down = e.clientX - dx; });
window.addEventListener('mousemove', e => { if (down === null) return; dx = Math.max(0, Math.min(280, e.clientX - down));
  h.style.left = dx + 'px'; pc.style.left = (dx * RATIO) + 'px'; });
window.addEventListener('mouseup', () => { if (down === null) return; down = null; window.landed = dx * RATIO;
  if (Math.abs(dx * RATIO - TARGET) <= 4) document.body.innerHTML = '<h1>Welcome</h1>' + '<p>Listings.</p>'.repeat(200);
  else { dx = 0; h.style.left = '0px'; pc.style.left = '0px'; } });
</script></body></html>"""


@pytest.mark.chrome
@pytest.mark.skipif(os.environ.get("CARHUNT_TEST_CHROME") != "1", reason="real browser smoke: CARHUNT_TEST_CHROME=1")
def test_solve_in_real_headless_chromium(carhunt_home, tmp_path):
    """detect -> discover parts -> image gap -> human drag with CDP input -> wall gone. Local page, no network."""
    sync_api = pytest.importorskip("playwright.sync_api")
    bg, piece, gx, _ = mf.puzzle(np.random.default_rng(21))
    url = lambda im: "data:image/png;base64," + base64.b64encode(cv2.imencode(".png", im)[1].tobytes()).decode()  # noqa: E731
    target = gx - (mf.PIECE_X + 1)
    html = _PAGE % dict(ratio="0.9", target=target, bg=url(bg), piece=url(piece))
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip(f"no Playwright Chromium: {e}")
        try:
            page = b.new_page(viewport={"width": 800, "height": 600})
            page.set_content(html)
            page.wait_for_function("window.ready === true")
            info = core.detect(page)
            assert info is not None and info.kind == "generic-slider"
            res = core.solve(page, route="plain", cfg=enabled(), use_vlm=False, outcome_timeout=6)
            assert res.status == "solved", (res.to_dict(), page.evaluate("window.landed"), target)
            assert res.attempts == 1
            assert abs(res.detail["attempt1"]["ratio"] - 0.9) < 0.1
        finally:
            b.close()
