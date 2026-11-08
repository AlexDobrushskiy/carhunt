"""Find slider parts (handle, track, puzzle background, piece) in a frame without knowing the vendor's markup."""
from __future__ import annotations

from .slider import Parts

_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.05; };
  const path = e => { const out = [];
    while (e && e.nodeType === 1 && e !== document.documentElement) {
      if (e.id && /^[A-Za-z][\w-]*$/.test(e.id) && document.querySelectorAll('#' + e.id).length === 1) { out.unshift('#' + e.id); break; }
      let i = 1, s = e; while ((s = s.previousElementSibling)) if (s.tagName === e.tagName) i++;
      out.unshift(e.tagName.toLowerCase() + ':nth-of-type(' + i + ')'); e = e.parentElement; }
    return (out[0] && out[0][0] === '#' ? '' : 'html > ') + out.join(' > '); };
  const box = e => { const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; };
  const cls = e => ((e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className) || '') + ' ' + (e.id || '');
  const all = [...document.querySelectorAll('body *')].filter(vis);
  const pics = all.filter(e => e.tagName === 'CANVAS' || e.tagName === 'IMG' || /url\(/.test(getComputedStyle(e).backgroundImage))
                  .filter(e => box(e).w >= 30 && box(e).h >= 30);
  pics.sort((a, b) => box(b).w * box(b).h - box(a).w * box(a).h);
  const bg = pics.find(e => box(e).w >= 150) || null;
  let piece = null;
  if (bg) { const B = box(bg);
    piece = pics.find(e => e !== bg && !e.contains(bg) && !bg.contains(e) && box(e).h >= 20 &&
        box(e).y >= B.y - 5 && box(e).y + box(e).h <= B.y + B.h + 5 && box(e).x <= B.x + B.w * 0.35 &&
        (box(e).w <= B.w * 0.45 || /slice|piece|block|puzzle|jigsaw|fragment/i.test(cls(e))))
      || pics.find(e => e !== bg && /slice|piece|block|jigsaw/i.test(cls(e)) && Math.abs(box(e).x - B.x) < 3 && Math.abs(box(e).w - B.w) < 3) || null; }
  const handleRe = /slider|handle|knob|drag|btn|button|thumb|arrow|icon/i;
  let best = null, bestScore = -1;
  for (const e of all) { const b = box(e);
    if (b.w < 18 || b.h < 18 || b.w > 110 || b.h > 110 || b.w / b.h > 2.4 || b.h / b.w > 2.4) continue;
    if (e === piece || e === bg || (piece && e.contains(piece))) continue;
    const c = cls(e); let s = 0;
    if (/toggle|reload|refresh|audio|close|info|logo|help|retry/i.test(c)) continue;
    if (handleRe.test(c)) s += 2;
    if (/handle|knob|thumb|slider.?(icon|btn|button)|btn|button/i.test(c)) s += 2;
    if (/slider/i.test(c + ' ' + cls(e.parentElement || e))) s += 2;
    if (e.getAttribute('role') === 'slider') s += 3;
    const cur = getComputedStyle(e).cursor; if (/pointer|grab|move|ew-resize/.test(cur)) s += 1;
    let a = e.parentElement, wide = null;
    for (let i = 0; i < 4 && a; i++, a = a.parentElement) { if (box(a).w >= b.w * 3 && box(a).h <= b.h * 2.5) { wide = a; break; } }
    if (wide) { s += 2; if (b.x - box(wide).x < b.w) s += 2; } else s -= 3;
    if (bg && b.y < box(bg).y + box(bg).h - 5) s -= 2;
    if (s > bestScore) { bestScore = s; best = {e, wide}; } }
  if (!best || bestScore < 4) return null;
  return {handle: path(best.e), track: best.wide ? path(best.wide) : null, bg: bg ? path(bg) : null,
          piece: piece ? path(piece) : null, score: bestScore,
          classes: {handle: cls(best.e).slice(0, 80), bg: bg ? cls(bg).slice(0, 80) : null, piece: piece ? cls(piece).slice(0, 80) : null}};
}"""


def discover(frame) -> tuple[Parts | None, dict]:
    try:
        r = frame.evaluate(_JS)
    except Exception as e:
        return None, {"error": str(e)[:200]}
    if not r: return None, {}
    return Parts(frame, r["handle"], r["bg"], r["piece"], r["track"]), r


KNOWN = {
    # vendor: list of (handle, bg, piece, track) selector sets tried before discovery
    # DataDome "Slide right to secure your access" (2026): handle .slider -> drop box .sliderTarget
    "datadome": [(".sliderContainer .slider", None, None, ".sliderContainer", ".sliderTarget"),
                 # puzzle variant (jigsaw-style canvases, hidden in the "simple" variant)
                 (".sliderContainer .slider", "#captcha__puzzle canvas:not(.block)", "#captcha__puzzle canvas.block", ".sliderContainer")],
    "geetest": [(".geetest_slider_button", ".geetest_canvas_bg", ".geetest_canvas_slice", ".geetest_slider_track"),
                (".geetest_btn", ".geetest_bg", ".geetest_slice_bg", ".geetest_track")],
}


def known_parts(frame, vendor) -> Parts | None:
    for sel in KNOWN.get(vendor, []):
        h, bg, pc, tr, goal = (tuple(sel) + (None,))[:5]
        has = lambda x: bool(x) and frame.locator(x).count() > 0
        try:
            if has(h) and frame.locator(h).first.is_visible():
                if vendor == "datadome" and goal and frame.locator("canvas:visible").count():
                    continue  # puzzle variant: next entry
                return Parts(frame, h, bg if has(bg) else None, pc if has(pc) else None,
                             tr if has(tr) else None, goal if has(goal) else None)
        except Exception:
            continue
    return None
