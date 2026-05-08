#!/usr/bin/env python3
"""
Extract BASE_DATA from index.html and emit Supabase-ready CSVs.
Outputs (in upload order):
  1_centers.csv
  2_business_units.csv
  3_teams.csv
  4_employment_types.csv
  5_positions.csv
  6_companies.csv
  7_employees.csv
  8_employee_history.csv
"""

import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
HTML = HERE.parent / "index.html"

# ─── 1. Pull BASE_DATA out of the HTML ───────────────────────────
src = HTML.read_text(encoding="utf-8")
m = re.search(r"const BASE_DATA\s*=\s*(\[.*?\])\s*;", src, re.DOTALL)
if not m:
    raise SystemExit("BASE_DATA not found")
data = json.loads(m.group(1))
print(f"Loaded {len(data)} employees from BASE_DATA")


# ─── 2. Build lookup tables (centers, BUs, teams) ────────────────
def clean(s):
    return (s or "").strip() or None

centers, bus, teams = {}, {}, {}      # name -> id (auto-incrementing)
bu_to_center, team_to_bu = {}, {}     # cross-refs

for e in data:
    c = clean(e.get("center"))
    b = clean(e.get("bu"))
    t = clean(e.get("team"))
    if c and c not in centers:
        centers[c] = len(centers) + 1
    # If a team exists under a center with no BU, create a placeholder BU
    if c and t and not b:
        b = "(직속)"
    if c and b:
        key = (c, b)
        if key not in bus:
            bus[key] = len(bus) + 1
            bu_to_center[bus[key]] = centers[c]
    if c and b and t:
        key = (c, b, t)
        if key not in teams:
            teams[key] = len(teams) + 1
            team_to_bu[teams[key]] = bus[(c, b)]


# ─── 3. Reference-table seeds ────────────────────────────────────
EMPLOYMENT_TYPES = [
    ("정규직원", "Full-time regular"),
    ("파견",     "On dispatch"),
    ("파견준비",  "Preparing for dispatch"),
    ("파견검토",  "Dispatch under review"),
    ("인턴",     "Intern"),
    ("한국파견",  "Dispatched from Korea HQ"),
]
POSITIONS = ["팀원", "리더", "팀장", "부장", "센터장", "임원", "CEO"]
COMPANIES = ["쿠콘", "비즈플레이", "경리나라", "비플페이", "웹케시", "코사인_공통"]

# Pull any extra wonka values that appear in BASE_DATA but not in the seed
extra = {clean(e.get("wonka")) for e in data} - {None} - set(COMPANIES)
COMPANIES.extend(sorted(extra))


# ─── 4. Helper to write CSV ──────────────────────────────────────
def write_csv(name, headers, rows):
    path = HERE / name
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    print(f"  wrote {path.name:32s} ({len(rows)} rows)")


# ─── 5. Org tables ───────────────────────────────────────────────
write_csv(
    "1_centers.csv",
    ["center_id", "name", "display_order"],
    [(cid, name, i + 1) for i, (name, cid) in enumerate(centers.items())],
)

write_csv(
    "2_business_units.csv",
    ["bu_id", "center_id", "name", "display_order"],
    [(bid, bu_to_center[bid], name, i + 1)
     for i, ((c, name), bid) in enumerate(bus.items())],
)

write_csv(
    "3_teams.csv",
    ["team_id", "bu_id", "name", "display_order"],
    [(tid, team_to_bu[tid], name, i + 1)
     for i, ((c, b, name), tid) in enumerate(teams.items())],
)

# ─── 6. Reference tables ─────────────────────────────────────────
write_csv(
    "4_employment_types.csv",
    ["type_code", "description"],
    EMPLOYMENT_TYPES,
)
write_csv(
    "5_positions.csv",
    ["position_code", "display_order"],
    [(p, i + 1) for i, p in enumerate(POSITIONS)],
)
write_csv(
    "6_companies.csv",
    ["company_id", "name", "display_order"],
    [(i + 1, n, i + 1) for i, n in enumerate(COMPANIES)],
)


# ─── 7. Employees ────────────────────────────────────────────────
def lookup_team_id(e):
    c, b, t = clean(e.get("center")), clean(e.get("bu")), clean(e.get("team"))
    if not t:
        return None
    if c and not b:
        b = "(직속)"
    return teams.get((c, b, t))

# Map name → emp_id for manager self-FKs.
# Frontend stores manager NAMES (e.g. '최기종'); we resolve to emp_id where we can.
name_to_id = {}
for e in data:
    nick_clean = re.sub(r"[\(\)]", "", clean(e.get("nick")) or "")
    name_clean = re.sub(r"\s*\(.*?\)", "", clean(e.get("name")) or "").strip()
    if nick_clean:
        name_to_id.setdefault(nick_clean, e["empId"])
    if name_clean:
        name_to_id.setdefault(name_clean, e["empId"])

def resolve_mgr(raw):
    if not raw:
        return None
    cleaned = re.sub(r"[\(\)]", "", raw).strip()
    return name_to_id.get(cleaned)  # None if external (e.g. HQ exec)

emp_headers = [
    "emp_id", "team_id", "bumun",
    "nick", "name", "gender", "join_date",
    "grade", "kgrade", "position_code", "jikmu",
    "employment_type", "wonka", "workplace",
    "local_mgr_id", "director_id", "dept_head_id",
    "status", "note",
    "dispatch_start", "dispatch_end", "dispatch_city",
    "dispatch_client", "dispatch_extendable",
]

emp_rows = []
for e in data:
    emp_rows.append([
        e["empId"],
        lookup_team_id(e),
        clean(e.get("bumun")),
        clean(e.get("nick")),
        clean(e.get("name")),
        clean(e.get("gender")),
        clean(e.get("join")),                         # 'join' → join_date
        clean(e.get("grade")),
        clean(e.get("kgrade")),
        clean(e.get("jikchak")),                      # → position_code
        clean(e.get("jikmu")),
        clean(e.get("type")),                         # → employment_type
        clean(e.get("wonka")),
        clean(e.get("workplace")),
        resolve_mgr(e.get("localMgr")),
        resolve_mgr(e.get("director")),
        resolve_mgr(e.get("deptHead")),
        clean(e.get("status")) or "재직",
        clean(e.get("note")),
        clean(e.get("dispatchStart")),
        clean(e.get("dispatchEnd")),
        clean(e.get("dispatchCity")),
        clean(e.get("dispatchClient")),
        "true" if e.get("dispatchExtendable") else "false",
    ])

write_csv("7_employees.csv", emp_headers, emp_rows)


# ─── 8. Employee history (statusHistory[]) ───────────────────────
hist_headers = [
    "history_id", "emp_id", "event_type", "event_date",
    "from_value", "to_value", "field_changed", "note", "recorded_by",
]
hist_rows = []
hid = 1
for e in data:
    for h in (e.get("statusHistory") or []):
        hist_rows.append([
            hid,
            e["empId"],
            clean(h.get("type")) or "변경",   # event_type
            clean(h.get("date")),              # event_date (may be empty)
            None,                              # from_value (unknown in legacy data)
            clean(h.get("type")),              # to_value
            "employment_type",
            clean(h.get("note")),
            "system_import",
        ])
        hid += 1

write_csv("8_employee_history.csv", hist_headers, hist_rows)

print("\n✅ Done. Upload to Supabase in numeric order (1 → 8).")
