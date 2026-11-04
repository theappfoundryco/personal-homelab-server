"""Draws the README banner and the GitHub social preview from the demo data and the project icon.
  python3 demo/readme_art.py        writes .github/assets/hero.png and .github/assets/social-preview.png
Same needs as demo/screenshots.py. Review the pictures before you commit them."""
import base64
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import screenshots as shots  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

ASSETS = os.path.join(ROOT, ".github", "assets")
PHONE = {"width": 390, "height": 844}
TABS = ["home", "journal", "gym", "sg"]

HERO = """<html><body style="margin:0;background:#161616;width:1600px;height:760px;display:flex;align-items:center;justify-content:center;gap:36px">
{phones}</body></html>"""
CARD = '<div style="width:300px;height:650px;border-radius:30px;overflow:hidden;border:1px solid #3a3a3a;background:#0f0f0f"><img src="data:image/png;base64,{b64}" style="display:block;width:300px"></div>'
SOCIAL = """<html><body style="margin:0;background:#222222;width:1280px;height:640px;display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:-apple-system,'Helvetica Neue',Arial,sans-serif">
<img src="data:image/svg+xml;base64,{icon}" style="width:300px;height:300px"><div style="margin-top:34px;color:#fff;font-size:56px;font-weight:500">Personal homelab server</div></body></html>"""


def b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def main():
    os.makedirs(ASSETS, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="hl-art-")
    srv, url = shots.server.start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx, pg = shots.open_page(browser, url, PHONE, 2)
        files = []
        for tab in TABS:
            shots.show(pg, tab)
            p = os.path.join(tmp, f"{tab}.png")
            pg.screenshot(path=p)  # one phone screen with its bottom menu, as a person sees it
            files.append(p)
        ctx.close()
        page = browser.new_page(viewport={"width": 1600, "height": 760}, device_scale_factor=1)
        page.set_content(HERO.format(phones="".join(CARD.format(b64=b64(f)) for f in files)))
        page.screenshot(path=os.path.join(ASSETS, "hero.png"))
        page = browser.new_page(viewport={"width": 1280, "height": 640}, device_scale_factor=1)
        page.set_content(SOCIAL.format(icon=b64(os.path.join(ASSETS, "icon.svg"))))
        page.screenshot(path=os.path.join(ASSETS, "social-preview.png"))
        browser.close()
    srv.shutdown()
    print("wrote hero.png and social-preview.png")


if __name__ == "__main__":
    main()
