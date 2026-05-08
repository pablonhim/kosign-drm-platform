#!/usr/bin/env python3
"""
Extract BASE_DATA into flat CSVs matching the simplified Supabase schema
(center/bu/team kept as TEXT columns on employees — no FK lookups).

Outputs:
  employees.csv         — one row per employee (26 columns)
  status_history.csv    — one row per statusHistory[] entry
"""

import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
HTML = HERE.parent / "index.html"

src = HTML.read_text(encoding="utf-8")
m = re.search(r"const BASE_DATA\s*=\s*(\[.*?\])\s*;", src, re.DOTALL)
if not m:
    raise SystemExit("BASE_DATA not found")
data = json.loads(m.group(1))
print(f"Loaded {len(data)} employees")


def clean(s):
    s = (s or "").strip()
    return s if s else None


def write_csv(name, headers, rows):
    path = HERE / name
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    print(f"  wrote {path.name:24s} ({len(rows)} rows)")


# ─── employees.csv ───────────────────────────────────────────────
emp_headers = [
    "emp_id",
    "nick", "name", "gender", "join_date",
    "grade", "kgrade", "jikchak", "jikmu",
    "employment_type", "wonka", "workplace",
    "bumun", "center", "bu", "team",
    "local_mgr", "director", "dept_head",
    "status", "note",
    "dispatch_start", "dispatch_end",
    "dispatch_city", "dispatch_client", "dispatch_extendable",
]

emp_rows = []
for e in data:
    emp_rows.append([
        e["empId"],
        clean(e.get("nick")),
        clean(e.get("name")),
        clean(e.get("gender")),
        clean(e.get("join")),                  # → join_date
        clean(e.get("grade")),
        clean(e.get("kgrade")),
        clean(e.get("jikchak")),
        clean(e.get("jikmu")),
        clean(e.get("type")),                  # → employment_type
        clean(e.get("wonka")),
        clean(e.get("workplace")),
        clean(e.get("bumun")),
        clean(e.get("center")),
        clean(e.get("bu")),
        clean(e.get("team")),
        clean(e.get("localMgr")),              # → local_mgr (kept as plain name)
        clean(e.get("director")),
        clean(e.get("deptHead")),              # → dept_head
        clean(e.get("status")) or "재직",
        clean(e.get("note")),
        clean(e.get("dispatchStart")),
        clean(e.get("dispatchEnd")),
        clean(e.get("dispatchCity")),
        clean(e.get("dispatchClient")),
        "true" if e.get("dispatchExtendable") else "false",
    ])

write_csv("employees.csv", emp_headers, emp_rows)


# ─── status_history.csv ──────────────────────────────────────────
# Skips history_id (BIGSERIAL auto-generates) and recorded_at (DEFAULT NOW())
hist_headers = ["emp_id", "event_type", "event_date", "note", "recorded_by"]

hist_rows = []
for e in data:
    for h in (e.get("statusHistory") or []):
        hist_rows.append([
            e["empId"],
            clean(h.get("type")) or "변경",
            clean(h.get("date")),
            clean(h.get("note")),
            "system_import",
        ])

write_csv("status_history.csv", hist_headers, hist_rows)

print("\n✅ Done. Upload employees.csv first, then status_history.csv.")
