#!/usr/bin/env python3
"""
Data-quality checker for BASE_DATA in index.html.

Run:
  python3 validate_employees.py
  python3 validate_employees.py --execs-csv execs.csv --users-csv users.csv
"""

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict, Counter

HTML = Path(__file__).parent / "index.html"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VALID_GENDER  = {"M", "F", ""}
VALID_STATUS  = {"재직", "퇴직", "휴직", ""}
VALID_TYPES   = {"정규직원", "파견", "파견준비", "파견검토", "인턴", "한국파견"}

# severity, emp_id, field, message
issues = []
def err(emp, field, msg):  issues.append(("ERROR", emp, field, msg))
def warn(emp, field, msg): issues.append(("WARN",  emp, field, msg))


# ─── CLI ─────────────────────────────────────────────────────────
ap = argparse.ArgumentParser(description="Validate BASE_DATA from index.html")
ap.add_argument("--execs-csv", help="CSV with at least a 'name' column")
ap.add_argument("--users-csv", help="CSV with at least a 'name' column")
args = ap.parse_args()


# ─── Load data ───────────────────────────────────────────────────
src = HTML.read_text(encoding="utf-8")
m = re.search(r"const BASE_DATA\s*=\s*(\[.*?\])\s*;", src, re.DOTALL)
if not m:
    sys.exit("BASE_DATA not found in index.html")
data = json.loads(m.group(1))


def names_from_csv(path):
    if not path:
        return set()
    out = set()
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            n = (row.get("name") or "").strip()
            if n:
                out.add(n)
    return out


def execs_from_html(src):
    """Parse DEFAULT_EXECS = [{id:'..',name:'..',title:'..'}, ...] from index.html."""
    block = re.search(r"const DEFAULT_EXECS\s*=\s*\[(.*?)\]\s*;", src, re.DOTALL)
    if not block:
        return set()
    return set(re.findall(r'name:\s*"([^"]+)"', block.group(1)))


# ─── Build helper indexes ────────────────────────────────────────
ids_seen = Counter(e.get("empId", "") for e in data)

# Map nick/name → emp_id for manager-reference checking
known_names = set()
for e in data:
    if e.get("nick"):
        known_names.add(re.sub(r"[\(\)]", "", e["nick"]).strip())
    if e.get("name"):
        known_names.add(re.sub(r"\s*\(.*?\)", "", e["name"]).strip())

# Merge in executives + users so HQ leaders aren't flagged as unknown
exec_names = execs_from_html(src) | names_from_csv(args.execs_csv)
user_names = names_from_csv(args.users_csv)
known_names |= exec_names | user_names


def parse_date(s, emp, field):
    """Return date or None. Logs errors."""
    if not s:
        return None
    if not DATE_RE.match(s):
        err(emp, field, f"invalid date format '{s}' (expected YYYY-MM-DD)")
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        err(emp, field, f"impossible date '{s}'")
        return None


# ─── Per-employee checks ─────────────────────────────────────────
today = date.today()
for e in data:
    emp = e.get("empId") or "(missing)"

    # 1. empId required + unique
    if not e.get("empId"):
        err(emp, "empId", "missing")
        continue
    if ids_seen[emp] > 1:
        err(emp, "empId", f"duplicate (appears {ids_seen[emp]} times)")

    # 2. Name presence
    if not e.get("nick") and not e.get("name"):
        warn(emp, "name", "both nick and name are empty")

    # 3. Gender
    if e.get("gender") not in VALID_GENDER:
        warn(emp, "gender", f"unexpected value '{e['gender']}' (expected M/F/empty)")

    # 4. Status
    if e.get("status") not in VALID_STATUS:
        warn(emp, "status", f"unknown status '{e['status']}'")

    # 5. Employment type
    etype = e.get("type", "")
    if etype and etype not in VALID_TYPES:
        warn(emp, "type", f"unknown employment_type '{etype}'")

    # 6. Date validity
    join = parse_date(e.get("join"),          emp, "join")
    ds   = parse_date(e.get("dispatchStart"), emp, "dispatchStart")
    de   = parse_date(e.get("dispatchEnd"),   emp, "dispatchEnd")

    if join and join > today:
        warn(emp, "join", f"join date {join} is in the future")

    # 7. Dispatch range sanity
    if ds and de and de < ds:
        err(emp, "dispatch", f"dispatchEnd ({de}) is before dispatchStart ({ds})")

    # 8. Dispatch / type consistency
    if etype == "파견" and not de:
        warn(emp, "dispatch", "type=파견 but dispatchEnd is empty")
    if etype not in ("파견", "파견준비", "파견검토", "한국파견"):
        if any(e.get(k) for k in ("dispatchStart", "dispatchEnd",
                                   "dispatchCity", "dispatchClient")):
            warn(emp, "dispatch",
                 f"type={etype or '(empty)'} but dispatch fields are populated")

    # 9. statusHistory dates
    for i, h in enumerate(e.get("statusHistory") or []):
        d = h.get("date")
        if d and not DATE_RE.match(d):
            err(emp, f"statusHistory[{i}].date",
                f"invalid date '{d}' (expected YYYY-MM-DD or empty)")


# ─── Aggregate: unknown manager-name references ──────────────────
# Collapse all (localMgr/director/deptHead) lookups into one summary
# line per unknown name, with the count of employees that reference it.
unknown_refs = defaultdict(lambda: defaultdict(set))   # name -> field -> {emp_ids}
for e in data:
    emp = e.get("empId") or "(missing)"
    for fld in ("localMgr", "director", "deptHead"):
        raw = e.get(fld) or ""
        if not raw:
            continue
        cleaned = re.sub(r"[\(\)]", "", raw).strip()
        if cleaned and cleaned not in known_names:
            unknown_refs[cleaned][fld].add(emp)

for name, fields in sorted(unknown_refs.items(), key=lambda x: -sum(len(v) for v in x[1].values())):
    parts = [f"{fld}×{len(ids)}" for fld, ids in fields.items()]
    total = sum(len(ids) for ids in fields.values())
    warn("(many)", "unknown_person",
         f"'{name}' referenced {total} times ({', '.join(parts)}) — "
         f"add to employees, executives, or users table")


# ─── Cross-employee: overlapping dispatch at the same client+city ──
# (Two people can share a client, so this is INFO-only — flagged as WARN
#  to surface possible mis-keyed rows.)
buckets = defaultdict(list)
for e in data:
    if e.get("type") == "파견" and e.get("dispatchStart") and e.get("dispatchEnd"):
        key = (e.get("dispatchClient", ""), e.get("dispatchCity", ""))
        ds = parse_date(e["dispatchStart"], e["empId"], "_overlap")
        de = parse_date(e["dispatchEnd"],   e["empId"], "_overlap")
        if ds and de:
            buckets[key].append((ds, de, e["empId"]))

# Pairwise overlap inside each (client, city) bucket
for key, items in buckets.items():
    items.sort()
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a_start, a_end, a_id = items[i]
            b_start, b_end, b_id = items[j]
            if b_start <= a_end:  # overlap
                warn(a_id, "dispatch_overlap",
                     f"period {a_start}..{a_end} overlaps {b_id} "
                     f"({b_start}..{b_end}) at client={key[0]} city={key[1]}")


# ─── Report ──────────────────────────────────────────────────────
errors = [i for i in issues if i[0] == "ERROR"]
warns  = [i for i in issues if i[0] == "WARN"]

print(f"\nValidated {len(data)} employee records\n")
print(f"  ERRORS: {len(errors)}")
print(f"  WARNS : {len(warns)}\n")

def print_group(label, group):
    if not group:
        return
    print(f"── {label} ──")
    for sev, emp, field, msg in group:
        print(f"  [{sev:5s}] {emp:10s} {field:24s} {msg}")
    print()

print_group("ERRORS (blocking — must fix before import)", errors)
print_group("WARNINGS (review recommended)", warns)

# Exit non-zero if there are errors (handy for CI / pre-commit)
sys.exit(1 if errors else 0)
