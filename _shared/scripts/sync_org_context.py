#!/usr/bin/env python3
"""Sync org context from Airtable and Google Docs into markdown files.

Usage:
    python3 sync_org_context.py --org-chart      # Sync org chart from People Ops
    python3 sync_org_context.py --lops            # Sync LOPs from SLT base
    python3 sync_org_context.py --strategy        # Sync strategy from Google Doc
    python3 sync_org_context.py --all             # Sync everything
    python3 sync_org_context.py --update-vault    # Update Obsidian people files with org data

Environment:
    AIRTABLE_API_KEY    — Required for --org-chart and --lops
    GOOGLE_DOCS_API_KEY — Optional for --strategy (falls back to gws CLI)
    OBSIDIAN_VAULT_PATH — Required for --update-vault
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

CONTEXT_DIR = Path(__file__).resolve().parent.parent / "context"

# Airtable config
PEOPLE_OPS_BASE = "appnXPTu01esWWbrK"
SLT_BASE = "appHDEHQA4bvlWwQq"       # SLT Meeting Intelligence (meetings, agenda, coaching)
LOP_BASE = "appAcnl4o8AQVZR1j"        # NSLS Goals / Level Order Planning (split 2026-05-01)
EMPLOYEES_TABLE = "tblpa8L4JPnqByINh"
L1_GOALS_TABLE = "tblFLHHpQUVpLrDjb"
L2_GOALS_TABLE = "tblpvFlUEy9GJflzB"

# Employee field IDs
EMP_NAME = "fldkA557zfIC2p8y2"
EMP_EMAIL = "fld3CmPWkul8GodI2"
EMP_SLACK = "fld3lm4bSBxV2tYVX"
EMP_DEPT = "fldIFpAjpTJpV965h"
EMP_TITLE = "fldVaevdMZwPc2NVu"
EMP_MANAGER = "fldDsdq5cCwMHMAjT"
EMP_STATUS = "fld8Wg5gwCEw6nCfw"

# L1 Goal field IDs
L1_THEME = "fldTVap09IVZHmgGi"
L1_SMART = "fldkgrP40za5d6wKn"
L1_DRI_USER = "fldJAWU95Xe0tioed"
L1_ACTIVE = "fldh5tsn6bTIbfAwk"
L1_YEAR = "fld5pzHuvIQh5sAzY"
L1_HEALTH = "fldn9BMtnN6eVm4NH"
L1_COMMENT = "fldNisSd2QmCh9cpf"

# L2 Goal field IDs
L2_NAME = "fld40ptzOdombUe0N"
L2_DRI_USER = "fldtkUyETBshr66uD"
L2_L1_GOAL = "fldzyHhzrh6mni3ND"
L2_STATUS = "fld1Pr6SUP7Z93iMK"
L2_YEAR = "fldP9xlZjm4y3giPo"
L2_HEALTH = "fldiXbqQQAfzq7gKT"
L2_COMMENT = "fldQrBwOTiCdjoSwn"
L2_DEADLINE = "fldqlzeaH1vGmvoVA"

# Google Doc
STRATEGY_DOC_ID = "1EOOTdKLV0j1MnpHV_hwNx4hbcOiHTjjKdo5h7UCZBYo"

TODAY = datetime.now().strftime("%Y-%m-%d")


def airtable_fetch(base_id, table_id, fields=None, filter_formula=None):
    """Fetch all records from an Airtable table with pagination."""
    api_key = os.environ.get("AIRTABLE_API_KEY")
    if not api_key:
        print("Error: AIRTABLE_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    records = []
    offset = None
    while True:
        params = ["returnFieldsByFieldId=true"]
        if fields:
            for f in fields:
                params.append(f"fields[]={f}")
        if filter_formula:
            params.append(f"filterByFormula={urllib.request.quote(filter_formula)}")
        if offset:
            params.append(f"offset={offset}")

        url = f"https://api.airtable.com/v0/{base_id}/{table_id}?{'&'.join(params)}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())

        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break
    return records


def sync_org_chart():
    """Sync org chart from People Ops Airtable."""
    print("Syncing org chart...", file=sys.stderr)

    fields = [EMP_NAME, EMP_EMAIL, EMP_SLACK, EMP_DEPT, EMP_TITLE, EMP_MANAGER, EMP_STATUS]
    records = airtable_fetch(PEOPLE_OPS_BASE, EMPLOYEES_TABLE, fields=fields)

    # Build lookup for manager names
    id_to_name = {r["id"]: r["fields"].get(EMP_NAME, "") for r in records}

    # Group active employees by department
    departments = {}
    for r in records:
        f = r["fields"]
        if f.get(EMP_STATUS) != "Active":
            continue
        dept = f.get(EMP_DEPT, "Unknown")
        if dept not in departments:
            departments[dept] = []

        manager_ids = f.get(EMP_MANAGER, [])
        manager_name = id_to_name.get(manager_ids[0], "") if manager_ids else ""

        departments[dept].append({
            "name": f.get(EMP_NAME, ""),
            "title": f.get(EMP_TITLE, ""),
            "manager": manager_name,
            "email": f.get(EMP_EMAIL, ""),
            "slack": f.get(EMP_SLACK, ""),
        })

    # Sort departments and employees
    lines = [
        "# NSLS Org Chart",
        f"_Last synced: {TODAY}_",
        "",
    ]

    for dept in sorted(departments.keys()):
        employees = sorted(departments[dept], key=lambda e: e["name"])
        lines.append(f"## {dept}")
        lines.append("")
        lines.append("| Name | Title | Manager | Email | Slack |")
        lines.append("|------|-------|---------|-------|-------|")
        for e in employees:
            slack = e["slack"] or ""
            lines.append(f"| {e['name']} | {e['title']} | {e['manager']} | {e['email']} | {slack} |")
        lines.append("")

    output = CONTEXT_DIR / "org-chart.md"
    output.write_text("\n".join(lines))

    # Also save JSON for vault updates and programmatic access
    all_employees = []
    for dept, emps in departments.items():
        for e in emps:
            all_employees.append({**e, "department": dept})

    # Build manages lookup (reverse of manager relationship)
    manages = {}
    for e in all_employees:
        mgr = e.get("manager", "")
        if mgr:
            manages.setdefault(mgr, []).append(e["name"])

    for e in all_employees:
        e["manages"] = sorted(manages.get(e["name"], []))

    json_output = CONTEXT_DIR / "org-chart.json"
    json_output.write_text(json.dumps(all_employees, indent=2))

    print(f"  Wrote {output} ({sum(len(d) for d in departments.values())} employees)", file=sys.stderr)


def sync_lops():
    """Sync LOPs from SLT Airtable base."""
    print("Syncing LOPs...", file=sys.stderr)

    # Fetch L1 Goals
    l1_fields = [L1_THEME, L1_SMART, L1_DRI_USER, L1_ACTIVE, L1_YEAR, L1_HEALTH, L1_COMMENT]
    l1_records = airtable_fetch(LOP_BASE, L1_GOALS_TABLE, fields=l1_fields)

    # Fetch L2 Goals
    l2_fields = [L2_NAME, L2_DRI_USER, L2_L1_GOAL, L2_STATUS, L2_YEAR, L2_HEALTH, L2_COMMENT, L2_DEADLINE]
    l2_records = airtable_fetch(LOP_BASE, L2_GOALS_TABLE, fields=l2_fields)

    # Index L2s by their L1 parent
    l2_by_l1 = {}
    for r in l2_records:
        f = r["fields"]
        if f.get(L2_STATUS) != "Active":
            continue
        l1_ids = f.get(L2_L1_GOAL, [])
        for l1_id in l1_ids:
            if l1_id not in l2_by_l1:
                l2_by_l1[l1_id] = []
            l2_by_l1[l1_id].append(r)

    lines = [
        "# Lines of Priority (LOPs)",
        f"_Last synced: {TODAY}_",
        "",
    ]

    # Render L1s with their L2s nested
    active_l1s = [r for r in l1_records if r["fields"].get(L1_ACTIVE) == "Active"]
    for r in active_l1s:
        f = r["fields"]
        theme = f.get(L1_THEME, "Untitled")
        smart = f.get(L1_SMART, "")
        dri_users = f.get(L1_DRI_USER, [])
        owner = dri_users[0].get("name", "Unassigned") if dri_users else "Unassigned"
        health_list = f.get(L1_HEALTH, [])
        health = health_list[0] if health_list else "No update"
        comment_list = f.get(L1_COMMENT, [])
        comment = comment_list[0] if comment_list else "No update yet."

        lines.append(f"## L1: {theme}")
        lines.append(f"**Owner**: {owner} | **Health**: {health}")
        if smart:
            lines.append(f"**Goal**: {smart}")
        lines.append(f"> {comment}")
        lines.append("")

        # Nested L2s
        l2s = l2_by_l1.get(r["id"], [])
        for l2r in l2s:
            l2f = l2r["fields"]
            l2_name = l2f.get(L2_NAME, "Untitled")
            l2_dri = l2f.get(L2_DRI_USER, [])
            l2_owner = l2_dri[0].get("name", "Unassigned") if l2_dri else "Unassigned"
            l2_health_list = l2f.get(L2_HEALTH, [])
            l2_health = l2_health_list[0] if l2_health_list else "No update"
            l2_comment_list = l2f.get(L2_COMMENT, [])
            l2_comment = l2_comment_list[0] if l2_comment_list else "No update yet."
            l2_deadline = l2f.get(L2_DEADLINE, "")

            lines.append(f"### L2: {l2_name}")
            deadline_str = f" | **Deadline**: {l2_deadline}" if l2_deadline else ""
            lines.append(f"**Owner**: {l2_owner} | **Health**: {l2_health}{deadline_str}")
            lines.append(f"> {l2_comment}")
            lines.append("")

    output = CONTEXT_DIR / "lops.md"
    output.write_text("\n".join(lines))
    count_l2 = sum(len(v) for v in l2_by_l1.values())
    print(f"  Wrote {output} ({len(active_l1s)} L1s, {count_l2} L2s)", file=sys.stderr)


def sync_strategy():
    """Sync strategy doc from Google Docs."""
    print("Syncing strategy...", file=sys.stderr)

    # Try gws CLI first (works locally with Kevin's auth)
    try:
        result = subprocess.run(
            [os.path.expanduser("~/bin/gws"), "docs", "documents", "get",
             "--params", json.dumps({"documentId": STRATEGY_DOC_ID})],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            # Parse gws output (may have keyring message on first line)
            output_lines = result.stdout.strip().split("\n")
            json_start = next(i for i, l in enumerate(output_lines) if l.strip().startswith("{"))
            doc = json.loads("\n".join(output_lines[json_start:]))
        else:
            raise RuntimeError(f"gws failed: {result.stderr}")
    except (FileNotFoundError, RuntimeError) as e:
        # Fallback: Google Docs API with API key or service account
        api_key = os.environ.get("GOOGLE_DOCS_API_KEY")
        if not api_key:
            print(f"  Error: gws not available ({e}) and GOOGLE_DOCS_API_KEY not set", file=sys.stderr)
            print("  Run this locally with gws, or set GOOGLE_DOCS_API_KEY for CI", file=sys.stderr)
            sys.exit(1)
        url = f"https://docs.googleapis.com/v1/documents/{STRATEGY_DOC_ID}?key={api_key}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            doc = json.loads(resp.read())

    # Convert Google Doc JSON to markdown
    title = doc.get("title", "NSLS Strategy")
    md_lines = [
        f"# {title}",
        f"_Last synced: {TODAY}_",
        f"_Source: [Google Doc](https://docs.google.com/document/d/{STRATEGY_DOC_ID}/edit)_",
        "",
    ]

    for elem in doc.get("body", {}).get("content", []):
        if "paragraph" not in elem:
            continue
        para = elem["paragraph"]
        style = para.get("paragraphStyle", {}).get("namedStyleType", "")

        # Extract text from all elements in the paragraph
        text = ""
        for el in para.get("elements", []):
            text += el.get("textRun", {}).get("content", "")
        text = text.strip()
        if not text:
            continue

        # Check for bullet/list items
        bullet = para.get("bullet")

        if "HEADING_1" in style:
            md_lines.append(f"\n## {text}")
        elif "HEADING_2" in style:
            md_lines.append(f"\n### {text}")
        elif "HEADING_3" in style:
            md_lines.append(f"\n#### {text}")
        elif bullet:
            nesting = bullet.get("nestingLevel", 0)
            indent = "  " * nesting
            md_lines.append(f"{indent}- {text}")
        else:
            md_lines.append(text)

    output = CONTEXT_DIR / "strategy.md"
    output.write_text("\n".join(md_lines) + "\n")
    print(f"  Wrote {output}", file=sys.stderr)


def update_vault():
    """Update Obsidian 30-people/ files with org chart frontmatter."""
    vault_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if not vault_path:
        # Try reading from personal toolkit .env
        env_file = Path.home() / ".claude/local-plugins/nsls-personal-toolkit/.env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("OBSIDIAN_VAULT_PATH="):
                    vault_path = line.split("=", 1)[1].strip()
                    break
    if not vault_path:
        print("Error: OBSIDIAN_VAULT_PATH not set and not found in personal toolkit .env", file=sys.stderr)
        sys.exit(1)

    # §3.3: create the write target if absent instead of erroring out. On a
    # Light-tier vault 30-people/ doesn't exist yet, and populating it is exactly
    # this sync's job — a missing dir is not an error (mirrors the companion's
    # ensure-vault-structure precedent). Genuine errors below still exit non-zero.
    people_dir = Path(vault_path) / "30-people"
    if not people_dir.exists():
        print(f"  30-people/ not found — creating {people_dir}", file=sys.stderr)
    people_dir.mkdir(parents=True, exist_ok=True)

    json_file = CONTEXT_DIR / "org-chart.json"
    if not json_file.exists():
        print("Error: org-chart.json not found. Run --org-chart first.", file=sys.stderr)
        sys.exit(1)

    employees = json.loads(json_file.read_text())
    print(f"Updating vault people files ({len(employees)} employees)...", file=sys.stderr)

    created = 0
    updated = 0
    for emp in employees:
        name = emp["name"]
        if not name:
            continue
        filepath = people_dir / f"{name}.md"

        # Fields to merge into frontmatter
        org_fields = {}
        if emp.get("title"):
            org_fields["role"] = emp["title"]
        if emp.get("department"):
            org_fields["department"] = emp["department"]
        if emp.get("email"):
            org_fields["email"] = emp["email"]
        if emp.get("slack"):
            org_fields["slack"] = emp["slack"]
        if emp.get("manager"):
            org_fields["reports-to"] = f"\"[[{emp['manager']}]]\""
        if emp.get("manages"):
            org_fields["manages"] = [f"\"[[{m}]]\"" for m in emp["manages"]]

        if filepath.exists():
            content = filepath.read_text()
            content = _merge_frontmatter(content, org_fields)
            filepath.write_text(content)
            updated += 1
        else:
            # Create a minimal stub
            fm_lines = ["---", "type: person", f"org: NSLS"]
            for k, v in org_fields.items():
                if isinstance(v, list):
                    fm_lines.append(f"{k}:")
                    for item in v:
                        fm_lines.append(f"  - {item}")
                else:
                    fm_lines.append(f"{k}: {v}")
            fm_lines.append("---")
            fm_lines.append("")
            fm_lines.append(f"# {name}")
            fm_lines.append("")
            filepath.write_text("\n".join(fm_lines))
            created += 1

    print(f"  Updated {updated}, created {created} people files", file=sys.stderr)


def _merge_frontmatter(content, new_fields):
    """Merge new fields into existing YAML frontmatter without clobbering other fields."""
    fm_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if not fm_match:
        # No frontmatter — prepend it
        fm_lines = ["---"]
        for k, v in new_fields.items():
            if isinstance(v, list):
                fm_lines.append(f"{k}:")
                for item in v:
                    fm_lines.append(f"  - {item}")
            else:
                fm_lines.append(f"{k}: {v}")
        fm_lines.append("---")
        return "\n".join(fm_lines) + "\n" + content

    fm_text = fm_match.group(1)
    body = content[fm_match.end():]

    # Parse frontmatter lines, preserving order
    fm_lines = fm_text.split("\n")
    existing_keys = set()
    for line in fm_lines:
        key_match = re.match(r"^(\w[\w-]*):", line)
        if key_match:
            existing_keys.add(key_match.group(1))

    # Update existing keys in place, append new ones at the end
    new_fm_lines = []
    skip_list_items = False
    for line in fm_lines:
        key_match = re.match(r"^(\w[\w-]*):", line)
        if key_match:
            key = key_match.group(1)
            skip_list_items = False
            if key in new_fields:
                val = new_fields[key]
                if isinstance(val, list):
                    new_fm_lines.append(f"{key}:")
                    for item in val:
                        new_fm_lines.append(f"  - {item}")
                    skip_list_items = True
                else:
                    # Don't overwrite role if person-intelligence set a richer one
                    # and Airtable has it empty
                    if key == "role" and not val:
                        new_fm_lines.append(line)
                    else:
                        new_fm_lines.append(f"{key}: {val}")
                continue
            else:
                new_fm_lines.append(line)
        elif skip_list_items and line.startswith("  - "):
            continue  # skip old list items we're replacing
        else:
            skip_list_items = False
            new_fm_lines.append(line)

    # Append keys that didn't exist yet
    for k, v in new_fields.items():
        if k not in existing_keys:
            if isinstance(v, list):
                new_fm_lines.append(f"{k}:")
                for item in v:
                    new_fm_lines.append(f"  - {item}")
            else:
                new_fm_lines.append(f"{k}: {v}")

    return "---\n" + "\n".join(new_fm_lines) + "\n---\n" + body


def main():
    parser = argparse.ArgumentParser(description="Sync org context to markdown")
    parser.add_argument("--org-chart", action="store_true", help="Sync org chart")
    parser.add_argument("--lops", action="store_true", help="Sync LOPs")
    parser.add_argument("--strategy", action="store_true", help="Sync strategy doc")
    parser.add_argument("--update-vault", action="store_true", help="Update Obsidian people files")
    parser.add_argument("--all", action="store_true", help="Sync everything")
    args = parser.parse_args()

    if not any([args.org_chart, args.lops, args.strategy, args.update_vault, args.all]):
        parser.print_help()
        sys.exit(1)

    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)

    if args.org_chart or args.all:
        sync_org_chart()
    if args.lops or args.all:
        sync_lops()
    if args.strategy or args.all:
        sync_strategy()
    if args.update_vault or args.all:
        update_vault()

    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
