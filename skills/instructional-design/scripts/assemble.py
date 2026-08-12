#!/usr/bin/env python3
"""Splice the bundled display font into a working guide file.

Usage: python3 assemble.py <guide.html>

Replaces the __FONT_B64__ token with the base64-encoded woff2 from
assets/bricolage-latin.woff2. Idempotent: exits cleanly if the token is
already spliced.
"""
import base64
import sys
from pathlib import Path

TOKEN = "__FONT_B64__"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    guide = Path(sys.argv[1])
    font = Path(__file__).resolve().parent.parent / "assets" / "bricolage-latin.woff2"

    html = guide.read_text()
    if TOKEN not in html:
        if "data:font/woff2;base64," in html:
            print("font already spliced; nothing to do")
            return 0
        print(f"error: {TOKEN} token not found in {guide}", file=sys.stderr)
        return 1

    b64 = base64.b64encode(font.read_bytes()).decode()
    guide.write_text(html.replace(TOKEN, b64))
    print(f"spliced {font.name} ({len(b64)} b64 chars) into {guide}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
