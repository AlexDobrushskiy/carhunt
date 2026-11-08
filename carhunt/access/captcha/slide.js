// Human-like slider drag for a Playwright MCP lane / identity tab without Python
// (pass this file's contents as `code` to browser_run_code_unsafe; print it with `carhunt captcha slide-js`).
// Handles the DataDome "Slide right to secure your access" slider (handle .slider -> drop box .sliderTarget,
// incl. the RETRY state) and plain "slide to the end" sliders. Puzzle sliders (a gap to find) need the
// Python solver (`carhunt captcha solve`) — it does the image work.
// DataDome in a Playwright-launched browser answered the correct slide with "Access is temporarily
// restricted" (10-26): on DataDome sites open the URL in plain-chrome and use `carhunt captcha solve --plain`.
// Returns {status, ...}. Never more than one drag per call; call at most twice per site.
async (page) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const rnd = (a, b) => a + Math.random() * (b - a);
  const minjerk = (t) => 10 * t ** 3 - 15 * t ** 4 + 6 * t ** 5;
  let mx = 0, my = 0;
  const vp = page.viewportSize() || { width: 1280, height: 800 };
  mx = vp.width * rnd(0.55, 0.9); my = vp.height * rnd(0.55, 0.9);
  async function seg(x1, y1, dur, arc = 0, trem = 0.4) {
    const x0 = mx, y0 = my, dx = x1 - x0, dy = y1 - y0, d = Math.hypot(dx, dy) || 1, nx = -dy / d, ny = dx / d;
    let t = 0, jx = 0, jy = 0, ax = 0, ay = 0;
    const start = Date.now();
    while (t < dur) {
      t = Math.min(dur, t + 1 / rnd(65, 125));
      const u = t / dur, s = minjerk(u), b = arc * Math.sin(Math.PI * s), f = u < 1 ? Math.sin(Math.PI * u) : 0;
      ax = 0.7 * ax + (Math.random() - 0.5) * 2 * trem; jx = 0.85 * jx + 0.15 * ax;
      ay = 0.7 * ay + (Math.random() - 0.5) * 2 * trem; jy = 0.85 * jy + 0.15 * ay;
      const wait = start + t * 1000 - Date.now(); if (wait > 0) await sleep(wait);
      mx = x0 + dx * s + nx * b + jx * f; my = y0 + dy * s + ny * b + jy * f;
      await page.mouse.move(mx, my);
    }
  }
  async function reach(x, y) {
    const dist = Math.hypot(x - mx, y - my);
    await seg(x + rnd(-2, 2), y + rnd(-2, 2), Math.min(1.1, 0.25 + 0.12 * Math.log2(1 + dist / 8) + rnd(-0.05, 0.12)),
              (Math.random() < 0.5 ? -1 : 1) * rnd(0.04, 0.12) * dist, 0.5);
    await sleep(rnd(30, 90)); await seg(x, y, rnd(0.08, 0.16), 0, 0.2);
  }
  const frame = page.frames().find((f) => /captcha-delivery\.com/.test(f.url())) || page.mainFrame();
  const box = async (sel) => { const l = frame.locator(sel).first(); return (await l.count()) && (await l.isVisible()) ? l.boundingBox() : null; };
  const retry = await box('button.retryLink');
  if (retry) { await reach(retry.x + retry.width * rnd(0.3, 0.7), retry.y + retry.height * rnd(0.3, 0.7));
    await sleep(rnd(80, 200)); await page.mouse.down(); await sleep(rnd(60, 140)); await page.mouse.up(); await sleep(rnd(2000, 3000)); }
  const h = await box('.sliderContainer .slider, [class*=slider][class*=handle], .slider');
  if (!h) return { status: 'no-slider', frame: frame.url().slice(0, 120) };
  const goal = await box('.sliderTarget');
  const track = await box('.sliderContainer, [class*=slider][class*=track], [class*=slider][class*=container]');
  const gx = h.x + h.width * rnd(0.35, 0.65), gy = h.y + h.height * rnd(0.35, 0.65);
  const dist = goal ? (goal.x + goal.width / 2) - (h.x + h.width / 2) + rnd(-2.5, 2.5)
                    : (track ? track.x + track.width - h.x - h.width + rnd(2, 6) : 260);
  await seg(mx + rnd(-3, 3), my + rnd(-3, 3), 0.05);
  await reach(gx, gy); await sleep(rnd(120, 350));
  await page.mouse.down(); await sleep(rnd(80, 200));
  const over = rnd(3, 9), yend = gy + rnd(-2.5, 2.5);
  await seg(gx + dist + over, yend, rnd(0.55, 0.95) + dist / rnd(900, 1400), rnd(-3, 3), 0.35);
  await sleep(rnd(60, 180));
  await seg(gx + dist, yend + rnd(-0.8, 0.8), rnd(0.15, 0.32), 0, 0.15);
  await sleep(rnd(100, 300)); await page.mouse.up();
  await sleep(4000);
  const dd = page.frames().find((f) => /captcha-delivery\.com\/captcha/.test(f.url()));
  const txt = dd ? await dd.evaluate(() => document.body.innerText).catch(() => '') : '';
  const status = !dd ? 'cleared' : /restricted|restreint|blocked|bloqu/i.test(txt) ? 'hard-block' : 'still-captcha';
  return { status, dist: Math.round(dist), url: page.url(), title: await page.title() };
}
