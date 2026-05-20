#!/usr/bin/env python3
"""
split_by_menu.py — Split index.html into per-menu standalone HTML files
under ./frontend/. Each output file is a full clone of the source EXCEPT
only that menu's <div class="page"> block is preserved in the main content
area, and the corresponding sidebar item is marked active.

Cross-page clicks navigate via a small patch to showPage(): if the
requested page isn't local to the current file, the function navigates
to <id>.html instead of toggling a non-existent <div class="page">.

No CSS, JS function, or mock data is removed — the only mutations are:
  1. Drop the OTHER page divs (keep one).
  2. Move the sidebar `.active` class to the right nav item.
  3. Insert a single navigation-guard block at the top of showPage().
  4. For outsourcing.html / rnd.html: append a tiny preset script that
     mirrors the prototype's VPAGE behavior (center pre-filter).

Run:  python3 split_by_menu.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC  = ROOT / "index.html"
OUT  = ROOT / "frontend"

if not SRC.exists():
    sys.exit(f"FATAL: {SRC} not found")
OUT.mkdir(exist_ok=True)

source = SRC.read_text(encoding="utf-8")
print(f"Loaded index.html: {len(source):,} bytes / {source.count(chr(10)) + 1} lines")

# ---------------------------------------------------------------------------
# Locate every <div class="page..." id="page-X"> ... </div> block.
# Walk forward from each opening tag, counting <div ...> opens and </div>
# closes until depth returns to 0. This handles nested divs cleanly without
# pulling in a full HTML parser.
# ---------------------------------------------------------------------------
PAGE_OPEN_RE = re.compile(r'<div class="page(?: active)?" id="page-([a-zA-Z0-9_-]+)"', re.IGNORECASE)

def locate_page_blocks(text: str) -> list[tuple[str, int, int]]:
    """Return [(page_id, start_index, end_index), ...] — end is exclusive."""
    DIV_OPEN_RE  = re.compile(r'<div\b', re.IGNORECASE)
    DIV_CLOSE_RE = re.compile(r'</div\s*>', re.IGNORECASE)
    blocks = []
    for m in PAGE_OPEN_RE.finditer(text):
        page_id = m.group(1)
        start = m.start()
        # Step past this opening <div ...> tag.
        tag_end = text.index('>', start) + 1
        depth = 1
        i = tag_end
        while depth > 0:
            next_open  = DIV_OPEN_RE.search(text,  i)
            next_close = DIV_CLOSE_RE.search(text, i)
            if next_close is None:
                raise RuntimeError(f"Unclosed <div> while scanning page '{page_id}'")
            if next_open is not None and next_open.start() < next_close.start():
                depth += 1
                i = next_open.end()
            else:
                depth -= 1
                i = next_close.end()
        blocks.append((page_id, start, i))
    return blocks

blocks = locate_page_blocks(source)
print(f"Found {len(blocks)} page blocks: {[b[0] for b in blocks]}")

# Sort blocks by their position so we can splice cleanly.
blocks_sorted = sorted(blocks, key=lambda b: b[1])

# ---------------------------------------------------------------------------
# Per-file generation
# ---------------------------------------------------------------------------
NAV_GUARD_JS = """  // ── MPA split (split_by_menu.py): if the target page isn't in this file,
  // navigate to the matching standalone HTML page instead of toggling a
  // non-existent <div class="page">. Filename === menu id by convention.
  try {
    const _currentFile_ = window.location.pathname.split('/').pop().replace('.html','');
    if (_currentFile_ && _currentFile_ !== id) {
      window.location.href = id + '.html';
      return;
    }
  } catch (_e) { /* fall through to original behavior */ }
"""

def build_file(*, keep_page_id: str, sidebar_active_id: str, preset_js: str = "") -> str:
    """
    Splice a new HTML document keeping only `keep_page_id`'s page block,
    flipping the sidebar's `.active` class to `sidebar_active_id`, patching
    showPage(), and optionally appending a preset-applying script.
    """
    parts = []
    last_end = 0
    for (pid, s, e) in blocks_sorted:
        parts.append(source[last_end:s])
        if pid == keep_page_id:
            # Normalize the kept block so it's marked .active on load.
            block = source[s:e]
            block = re.sub(
                r'<div class="page(?: active)?" id="page-' + re.escape(pid) + r'"',
                f'<div class="page active" id="page-{pid}"',
                block, count=1,
            )
            parts.append(block)
        # Else: drop this page entirely.
        last_end = e
    parts.append(source[last_end:])
    out = "".join(parts)

    # Move sidebar `.active` to the requested nav item. Remove any existing
    # `active` on `.navi` rows first, then add it to the chosen one.
    out = re.sub(r'<div class="navi active"', '<div class="navi"', out)
    out = out.replace(
        f'<div class="navi" id="nav-{sidebar_active_id}"',
        f'<div class="navi active" id="nav-{sidebar_active_id}"',
        1,
    )

    # Insert the navigation guard right after `function showPage(id){`.
    out, n = re.subn(
        r'(function\s+showPage\s*\(\s*id\s*\)\s*\{)',
        lambda m: m.group(1) + "\n" + NAV_GUARD_JS,
        out, count=1,
    )
    if n == 0:
        print("  WARN: showPage(id) signature not found — nav guard NOT inserted", file=sys.stderr)

    # Optional preset script (outsourcing / rnd).
    if preset_js:
        out = out.replace(
            "</body>",
            "<script>\n// MPA preset (split_by_menu.py): mirrors the prototype's VPAGE behavior\n"
            + preset_js + "\n</script>\n</body>",
            1,
        )

    return out


# ---------------------------------------------------------------------------
# Per-menu plan. Each entry: (filename, page-id to keep, sidebar nav id, preset JS)
# outsourcing & rnd reuse the `list` page block and auto-apply their center filter
# on load — matching what the prototype's VPAGE indirection does in the SPA.
# ---------------------------------------------------------------------------
PRESET_OUTSOURCING = """
document.addEventListener('DOMContentLoaded', function() {
  // Apply '아웃소싱/파견센터' to the centre multi-select once startApp() has
  // populated the filter widgets. Retry briefly in case Supabase load is slow.
  let tries = 0;
  (function apply() {
    if (typeof msSet === 'function' && document.querySelector('.ms-wrap[data-key="fc"] .ms-list input')) {
      msSet('fc', '아웃소싱/파견센터');
      const fcWrap = document.querySelector('.ms-wrap[data-key="fc"]');
      if (fcWrap) fcWrap.style.display = 'none';
    } else if (tries++ < 40) {
      setTimeout(apply, 150);
    }
  })();
});
""".strip()

PRESET_RND = """
document.addEventListener('DOMContentLoaded', function() {
  let tries = 0;
  (function apply() {
    if (typeof msSet === 'function' && document.querySelector('.ms-wrap[data-key="fc"] .ms-list input')) {
      msSet('fc', 'R&D 지원센터');
      const fcWrap = document.querySelector('.ms-wrap[data-key="fc"]');
      if (fcWrap) fcWrap.style.display = 'none';
    } else if (tries++ < 40) {
      setTimeout(apply, 150);
    }
  })();
});
""".strip()

TARGETS = [
    # (filename,              keep_page_id,    sidebar_active_id,  preset_js)
    ("dashboard.html",        "dashboard",     "dashboard",        ""),
    ("list.html",             "list",          "list",             ""),
    ("outsourcing.html",      "list",          "outsourcing",      PRESET_OUTSOURCING),
    ("dispatch.html",         "dispatch",      "dispatch",         ""),
    ("rnd.html",              "list",          "rnd",              PRESET_RND),
    ("summary.html",          "summary",       "summary",          ""),
    ("settings-org.html",     "settings-org",  "settings-org",     ""),
    ("settings-users.html",   "settings-users","settings-users",   ""),
    ("changelog.html",        "changelog",     "changelog",        ""),
]

print()
for (filename, keep_id, nav_id, preset) in TARGETS:
    content = build_file(keep_page_id=keep_id, sidebar_active_id=nav_id, preset_js=preset)
    (OUT / filename).write_text(content, encoding="utf-8")
    sz = (OUT / filename).stat().st_size
    print(f"  wrote frontend/{filename:<24} {sz:>9,} bytes")

print()
print("Done. 9 files written under frontend/.")
print("Open any of them directly — they navigate between each other via showPage().")
