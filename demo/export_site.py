"""Exports the dashboard as a static demo with the fake demo data, for the website (theappfoundry.co/homelab/demo/).
It runs the real dashboard against the demo data, clicks through every page while recording what the assistant answers,
then writes the site, the module views and those answers to a folder. A small script in the page serves the recorded answers
in the browser, keeps ticks and spending in memory, and says that changes are not saved. Nothing personal is involved.
  pip install playwright pyyaml && playwright install chromium
  python3 demo/export_site.py <folder>        for example ../theappfoundryco/public/homelab/demo"""
import json
import os
import re
import shutil
import sys
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "tests", "e2e"), os.path.join(ROOT, "tests")]
sys.path.insert(0, HERE)
import server  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from screenshots import forecast, open_page  # noqa: E402  (healthy status and a made-up forecast, as in the README pictures)

SITE = os.path.join(ROOT, "stack", "landing", "site")
INSTALL = "https://theappfoundry.co/homelab/install"
SHIM = r"""<script>
// Demo: answers come from api.json (recorded from the real dashboard with fake data). Nothing is saved.
(() => {
  const real = window.fetch.bind(window), BASE = location.pathname.replace(/[^/]*$/, '');
  let API = null; const ready = real(BASE + 'api.json').then((r) => r.json()).then((j) => { API = j; });
  const mem = {};  // ticks and spending, kept until the page is closed
  const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  const note = () => { const b = document.getElementById('demo-bar'); if (b) { b.classList.add('pulse'); setTimeout(() => b.classList.remove('pulse'), 1200); } };
  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    if (url.startsWith('https://api.open-meteo.com/')) { await ready; return json(API.__weather); }  // the same made-up weather as the pictures
    if (url.startsWith('https://air-quality-api.open-meteo.com/')) { await ready; return json(API.__air); }
    if (!url.startsWith('/') || url.startsWith('//')) return real(input, init);
    await ready;
    const u = new URL(url, location.origin), method = (init.method || 'GET').toUpperCase();
    if (method === 'HEAD') return new Response(null, { status: 200, headers: { etag: 'demo' } });
    let path = u.pathname.replace(/^\/api\/bot/, ''); const key = path + u.search;
    if (method === 'GET') {
      if (mem[key]) return json(mem[key]);
      if (API[key]) return json(API[key]);
      if (API[path]) return json(API[path]);
      return json({ ok: false, msg: 'Not part of the demo.' }, 404);
    }
    note();
    let body = {}; try { body = JSON.parse(init.body || '{}'); } catch (e) {}
    if (path === '/sg/tick') { const v = JSON.parse(JSON.stringify(mem['/sg'] || API['/sg'])); (v.log[body.date] ||= {})[body.id] = !!body.done; if (!body.done) delete v.log[body.date][body.id]; mem['/sg'] = v; return json(v); }
    if (path.startsWith('/sg/')) return json(mem['/sg'] || API['/sg']);
    if (path === '/money/spent') {
      const k = '/money' + u.search, v = JSON.parse(JSON.stringify(mem[k] || API[k] || API['/money']));
      if (v.shown) { const a = Math.round(parseFloat(String(body.amount).replace(/[^0-9.]/g, '')) * 100) || 0;
        v.spent.unshift({ id: 'd' + Date.now(), amount: a, note: body.note || '', day: body.day });
        v.spent_today += body.day === +v.today.slice(8) ? a : 0; v.total_spent += a; v.left_today -= body.day === +v.today.slice(8) ? a : 0; v.left_month -= a; }
      mem[k] = v; return json(v);
    }
    if (path.startsWith('/money/')) return json(mem['/money' + u.search] || API['/money' + u.search] || API['/money']);
    return json({ ok: false, msg: 'This does not work in the demo. Install your own to try it.' }, 400);
  };
})();
</script>
<style>
#demo-bar { position: fixed; z-index: 90; left: 50%; bottom: calc(76px + env(safe-area-inset-bottom)); transform: translateX(-50%); display: flex; gap: 10px; align-items: center;
  padding: 8px 14px; border-radius: 999px; background: var(--inv); color: var(--on-inv); font: 600 13px/1.2 Inter, system-ui, sans-serif; box-shadow: var(--shadow); white-space: nowrap; transition: transform .2s; }
#demo-bar a { color: inherit; opacity: .8; }
#demo-bar.pulse { transform: translateX(-50%) scale(1.06); }
</style>"""
BAR = f'<div id="demo-bar">Demo with fake data, nothing is saved <a href="{INSTALL}" target="_top">Get your own</a></div>'


def record(url):
    """Visits every page of the dashboard and returns {path?query: answer} for each GET to the assistant."""
    seen = {}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx, p = open_page(b, url, {"width": 390, "height": 844}, 1)

        def keep(r):
            u = urlsplit(r.url)
            if r.request.method == "GET" and u.path.startswith("/api/") and r.ok:
                try:
                    seen[u.path.removeprefix("/api/bot") + (f"?{u.query}" if u.query else "")] = r.json()
                except Exception:
                    pass
        p.on("response", keep)
        p.reload()
        p.wait_for_timeout(3000)
        for tab in ("journal", "gym", "sg", "server", "home"):
            p.evaluate(f"showTab('{tab}')")
            p.wait_for_timeout(1500)
        p.evaluate("showTab('sg')"); p.wait_for_timeout(800)
        for m in ("2026-10", "2026-12"):
            p.evaluate(f"sgCal('{m}')"); p.wait_for_timeout(400)
        p.click('[data-mnseg="money"]'); p.wait_for_timeout(1200)
        p.click("[data-mneye]"); p.wait_for_timeout(1000)
        p.click('[data-mnseg="health"]'); p.wait_for_timeout(300)
        for open_ in ("#weather", "#brief-open", "#news-open", "#planner-open", "#hw-open", "#nl-open"):
            try:
                p.evaluate(f"document.querySelector('{open_}')?.click()"); p.wait_for_timeout(1200)
                p.keyboard.press("Escape")
            except Exception:
                pass
        p.evaluate("openSettings()"); p.wait_for_timeout(1500)
        pages = p.evaluate("[...document.querySelectorAll('#set-body [data-go]')].map((b) => b.dataset.go).filter(Boolean)")
        for page in pages + ["backups", "update"]:
            p.evaluate(f"SET.page = '{page}'; setRender()"); p.wait_for_timeout(1200)
        b.close()
    return seen


def main(out):
    srv, url = server.start()
    api = record(url)
    srv.shutdown()
    if os.path.isdir(out):
        shutil.rmtree(out)
    shutil.copytree(SITE, out, ignore=shutil.ignore_patterns(".DS_Store"))
    for mod in sorted(os.listdir(os.path.join(ROOT, "modules"))):
        web = os.path.join(ROOT, "modules", mod, "web")
        if os.path.isdir(web):
            shutil.copytree(web, os.path.join(out, "m", mod, "web"))
    api["__weather"], api["__air"] = forecast(), {"current": {"us_aqi": 32, "pm2_5": 7.0}}
    with open(os.path.join(out, "api.json"), "w") as f:
        json.dump(api, f, separators=(",", ":"))
    p = os.path.join(out, "index.html")
    html = open(p).read()
    html = re.sub(r'(href|src)="/(?!/)', r'\1="', html)  # the icons and manifest, relative to the demo folder
    html = html.replace("<script", SHIM + "\n<script", 1).replace("</body>", BAR + "\n</body>", 1)
    html = html.replace('<meta name="viewport"', '<meta name="robots" content="noindex">\n<meta name="viewport"', 1)
    open(p, "w").write(html)
    lp = os.path.join(out, "js", "loader.js")
    text = open(lp).read()
    assert "`/m/${m.name}/web/${f}`" in text, "the loader changed: update the module path rewrite here"
    open(lp, "w").write(text.replace("`/m/${m.name}/web/${f}`", "`m/${m.name}/web/${f}`"))
    print(f"wrote the demo to {out}: {len(api)} recorded answers")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(os.path.abspath(sys.argv[1]))
