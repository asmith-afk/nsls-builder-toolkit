# UI screenshots — capture, annotate, embed

A step like "press the + button at the bottom" deserves a small annotated
picture of the real control. This file covers how to get one honestly in
each environment, and the house annotation style.

## Rule zero: real pixels or nothing

Never draw, mock, or AI-generate a picture of an application's UI and pass
it off as a screenshot. A fabricated screenshot that drifts from the real
app actively harms the reader ("my screen doesn't look like that — I must
have broken something"). If you cannot capture the real UI, ask the user to
provide screenshots — they can paste images directly into chat. Give them a
short shot list: "I need: (1) the bottom bar showing the + button, (2) the
dialog that opens after clicking it." A schematic pointer graphic (plain
labeled arrow/box, obviously not a screenshot) is acceptable only as a
clearly-styled diagram, never as a fake capture.

## Capture by environment

- **Remote/cloud session (no display access to the user's machine)**: you
  cannot see their desktop apps. Ask for pasted screenshots (shot list
  above). For *web* UIs you can reach, capture with headless Chromium via
  playwright-core (`npm install playwright-core`; launch with
  `executablePath: '/opt/pw-browsers/chromium'` if present) at
  `deviceScaleFactor: 2` for crisp text.
- **Local macOS session**: `screencapture -x out.png` (full screen) or
  `screencapture -l <windowid> -x out.png` for a specific window
  (list windows via `osascript` or `GetWindowID`). Requires the user to
  have the target app visible; tell them before you fire it.
- **Screenshot provided by user**: confirm which control/region matters
  before cropping.

## Crop

Crop tight to the control plus enough surrounding context to locate it
(the whole toolbar, not the whole window; the corner of the window if
position is the point). Target display width ≤ 600px inside the guide.
Capture at 2× scale so the crop stays sharp. Python Pillow or another
Playwright `clip` pass both work for cropping.

## Annotate — house style

One ring, in the path color, around the control being pointed at. Do the
annotation in HTML/CSS (keeps the image untouched and the style consistent):

```html
<figure class="shot">
  <div class="shot-frame">
    <img src="data:image/png;base64,..." alt="The Claude Code window's bottom bar; the + button sits at the far left." width="560">
    <span class="shot-ring" style="left: 4%; top: 62%; width: 9%; height: 26%;"></span>
  </div>
  <figcaption>The <span class="ui">+</span> button lives at the bottom-left of the window.</figcaption>
</figure>
```

```css
.shot { margin: 0.9rem 0 0; }
.shot-frame { position: relative; display: inline-block; max-width: 100%; }
.shot-frame img {
  display: block; max-width: 100%; height: auto;
  border: 1px solid var(--line); border-radius: 10px; box-shadow: var(--shadow);
}
.shot-ring {
  position: absolute; border: 3px solid var(--path); border-radius: 999px;
  box-shadow: 0 0 0 2px rgba(255,255,255,0.6); pointer-events: none;
}
.shot figcaption {
  font-size: 0.85rem; color: var(--ink-soft); margin-top: 0.4rem;
}
```

Add these styles to the working file when first needed (they're not in the
template to keep it lean). Position the ring with percentage offsets so it
tracks the image at any size. One ring per image; if you need two rings,
you need two crops.

Alt text describes what the reader should find, not "screenshot of app".

## Embed

Base64 the cropped PNG into a `data:` URI (`base64 < crop.png | tr -d '\n'`). Keep
each embedded image under ~150KB (2× PNG of a tight crop lands well under
this; if not, crop tighter or use JPEG for photographic content). The guide
must stay a single self-contained file — no external image references.

## Staleness

Screenshots rot when the app updates. Put the app version in the guide
footer when screenshots are present, and tell the user which images to
re-request when the UI changes. This is another reason to use screenshots
only where words genuinely fail (see content-decisions.md).
