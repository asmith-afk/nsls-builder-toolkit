---
name: receipts
description: Find Ramp transactions missing receipts, fetch each receipt from Anthropic's billing API or Gmail, and upload it to Ramp against the exact transaction. Use when the user says "receipts", "/receipts", "missing receipts", "Ramp needs a receipt", "receipt cleanup", or forwards a Ramp "transaction needs a receipt" nag. Dry run by default.
---

# Receipts → Ramp

Clears Ramp's missing-receipt queue. Dry run by default; `--send` executes.

## Usage

- `/receipts` — show the plan, change nothing
- `/receipts --send` — execute
- `/receipts --since 2026-01-01` — widen the window (default: 2026-01-01)

Requires `ramp auth login`. Gmail sourcing additionally requires `gws auth login`.
