#!/usr/bin/env python3
"""Verify a built guide: contrast checks, theme renders, sections, PDF.

Usage:
  python3 verify.py <guide.html>               # contrast + light/dark full-page PNGs
  python3 verify.py <guide.html> --sections    # also emit chat-readable section PNGs
  python3 verify.py <guide.html> --pdf         # also emit a PDF via the print CSS

Rendering needs Node with playwright-core installed in the working
directory (`npm install playwright-core`) and a Chromium binary — the
script tries $PLAYWRIGHT_CHROMIUM, /opt/pw-browsers/chromium, then
playwright-core's own default. Contrast checks always run; rendering
degrades gracefully with a warning if Chromium is unavailable.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# Token pairs that carry small text; AA floor 4.5:1.
CONTRAST_PAIRS = [
    ("--done", "--done-ground", "done-strip label"),
    ("--ink", "--ground", "body on sheet"),
    ("--ink", "--card", "body on card"),
    ("--ink-soft", "--card", "secondary on card"),
    ("--warn", "--warn-ground", "callout label"),
    ("--path", "--ground", "eyebrow on sheet"),
]


def luminance(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    rgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def extract_tokens(css: str, block_start: str) -> dict:
    """Pull --token: #hex declarations from the first block after block_start."""
    idx = css.find(block_start)
    if idx == -1:
        return {}
    end = css.find("}", idx)
    if end == -1:
        return {}  # malformed/truncated block — treat like a missing theme
    body = css[idx:end]
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9A-Fa-f]{6})", body))


def check_contrast(html: str) -> bool:
    ok = True
    light = extract_tokens(html, ":root {")
    media_dark = extract_tokens(html, "@media (prefers-color-scheme: dark)")
    toggle_dark = extract_tokens(html, ':root[data-theme="dark"]')
    toggle_light = extract_tokens(html, ':root[data-theme="light"]')
    themes = {
        "light": light,
        # Media block overrides inherit from :root — a partial override is
        # legitimate. Guarded so an absent block still fails, never passes
        # as light.
        "dark (media)": {**light, **media_dark} if media_dark else {},
        # Manual-toggle cascades — what readers actually get when the theme
        # toggle overrides the OS preference: base tokens, then the OS media
        # block (dark OS), then the explicit data-theme override. An empty or
        # missing override block fails below like a missing theme.
        "dark (toggle)": {**light, **toggle_dark} if toggle_dark else {},
        "light (toggle)": {**light, **media_dark, **toggle_light} if toggle_light else {},
    }
    for theme, tokens in themes.items():
        if not tokens:
            print(f"  [FAIL] {theme}: theme block missing or has no tokens")
            ok = False
            continue
        for fg, bg, label in CONTRAST_PAIRS:
            if fg not in tokens or bg not in tokens:
                missing = ", ".join(t for t in (fg, bg) if t not in tokens)
                print(f"  [FAIL] {theme} {label}: missing token(s) {missing}")
                ok = False
                continue
            r = ratio(tokens[fg], tokens[bg])
            status = "PASS" if r >= 4.5 else "FAIL"
            if r < 4.5:
                ok = False
            print(f"  [{status}] {theme} {label}: {tokens[fg]} on {tokens[bg]} = {r:.2f}:1")
    return ok


NODE_RENDER = """
const { chromium } = require('playwright-core');
const cfg = JSON.parse(process.argv[1]);
(async () => {
  const opts = cfg.executablePath ? { executablePath: cfg.executablePath } : {};
  const browser = await chromium.launch(opts);
  for (const scheme of ['light', 'dark']) {
    const page = await browser.newPage({
      viewport: { width: 1000, height: 900 }, deviceScaleFactor: 2, colorScheme: scheme });
    await page.goto('file://' + cfg.file);
    await page.waitForTimeout(400);
    await page.screenshot({ path: cfg.stem + '-' + scheme + '.png', fullPage: true });
    if (scheme === 'light' && cfg.sections) {
      const total = await page.evaluate(() => document.documentElement.scrollHeight);
      const chunk = 950;
      let i = 1;
      for (let y = 0; y < total; y += chunk) {
        const h = Math.min(chunk, total - y);
        if (h < 80) break;
        await page.screenshot({ path: `${cfg.stem}-sec-${i}.png`, fullPage: true,
          clip: { x: 0, y, width: 1000, height: h } });
        i++;
      }
      console.log('sections:', i - 1);
    }
    if (scheme === 'light' && cfg.pdf) {
      await page.emulateMedia({ media: 'print' });
      await page.pdf({ path: cfg.stem + '.pdf', format: 'Letter',
        printBackground: true, margin: { top: '0.4in', bottom: '0.4in' } });
      await page.emulateMedia({ media: 'screen' });
      console.log('pdf written');
    }
    await page.close();
  }
  await browser.close();
  console.log('renders done');
})();
"""


def find_chromium() -> str | None:
    import os
    for candidate in (os.environ.get("PLAYWRIGHT_CHROMIUM"), "/opt/pw-browsers/chromium"):
        if candidate and Path(candidate).exists():
            return candidate
    return None  # let playwright-core resolve its own


def render(guide: Path, sections: bool, pdf: bool) -> None:
    cfg = json.dumps({
        "file": str(guide.resolve()),
        "stem": str(guide.resolve().with_suffix("")),
        "sections": sections,
        "pdf": pdf,
        "executablePath": find_chromium(),
    })
    try:
        proc = subprocess.run(
            ["node", "-e", NODE_RENDER, cfg],
            capture_output=True, text=True, cwd=guide.resolve().parent,
        )
    except (FileNotFoundError, OSError):
        print("  warning: node not installed — render step skipped")
        return
    print(proc.stdout.strip())
    if proc.returncode != 0:
        print("  warning: render step failed (is playwright-core installed here?)")
        print("  " + (proc.stderr or "").strip()[:400])


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        return 2
    guide = Path(args[0])
    html = guide.read_text()

    print("contrast:")
    ok = check_contrast(html)

    if "__FONT_B64__" in html:
        print("  [FAIL] font token not spliced — run assemble.py first")
        ok = False
    if 'name="viewport"' not in html:
        print("  [FAIL] viewport meta missing — mobile breakpoints will not fire")
        ok = False

    render(guide, "--sections" in sys.argv, "--pdf" in sys.argv)
    print("verify:", "all pass" if ok else "FAILURES above — fix before shipping")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
