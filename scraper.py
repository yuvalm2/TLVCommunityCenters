#!/usr/bin/env python3
"""
Scraper for Tel Aviv community center (matnas) classes and activities.
Calls the municipality API directly — no browser needed.

Usage:
    python scraper.py                           # all activities
    python scraper.py --matnas "רמת אביב"      # filter by center name
    python scraper.py --category "יוגה"        # filter by name/category keyword
    python scraper.py --scope "ספורט"          # filter by scope
    python scraper.py --available              # only activities with open spots
    python scraper.py --output csv             # csv / json / both / none (default: both)
    python scraper.py --diff                   # compare against last snapshot & save new one
    python scraper.py --list-centers           # print all center names
    python scraper.py --list-categories        # print all category/scope names
"""

import asyncio
import json
import csv
import argparse
import io
import sys
from pathlib import Path
from datetime import datetime

import aiohttp

# Force UTF-8 on Windows so Hebrew prints correctly
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

API_URL = (
    "https://www.tel-aviv.gov.il"
    "/_vti_bin/TlvSP2013PublicSite/TlvListUtils.svc/GetActivities/false/"
)

HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
    "Referer": "https://www5.tel-aviv.gov.il/TlvCommunity/activities/activities-list",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

OUT_DIR = Path(__file__).parent / "output"
SNAPSHOT_FILE = OUT_DIR / "snapshot_latest.json"

# Fields compared when diffing two snapshots
DIFF_FIELDS = ["name", "matnas", "category", "price", "available", "total", "days", "instructor"]


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

async def fetch_data() -> dict:
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(API_URL, ssl=False) as resp:
            resp.raise_for_status()
            text = await resp.text()
            data = json.loads(text)
            # The API double-encodes: outer layer is a JSON string wrapping the real object
            if isinstance(data, str):
                data = json.loads(data)
            return data


# ---------------------------------------------------------------------------
# Normalise one activity
# ---------------------------------------------------------------------------

def fmt_date(raw: str) -> str:
    """/Date(ms)/ → YYYY-MM-DD, or pass through ISO strings."""
    if not raw:
        return ""
    if raw.startswith("/Date("):
        ms = int(raw[6:raw.index(")")])
        return datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d")
    return raw[:10]


def fmt_times(weekly: list) -> str:
    if not weekly:
        return ""
    parts = []
    for t in weekly:
        if isinstance(t, str):
            try:
                t = json.loads(t)
            except Exception:
                parts.append(t)
                continue
        if isinstance(t, dict):
            day = t.get("Value", "")
            frm = t.get("new_from", "")
            to  = t.get("new_to", "")
            parts.append(f"{day} {frm}-{to}".strip("-").strip())
        else:
            parts.append(str(t))
    return " | ".join(parts)


def fmt_audience(targets: list) -> str:
    if not targets:
        return ""
    return ", ".join(t.get("AudienceName", "") for t in targets if isinstance(t, dict))


def normalise(a: dict) -> dict:
    institute = a.get("Institute") or {}
    category  = a.get("Category")  or {}
    scope     = a.get("Scope")     or {}
    sub       = a.get("SubCategory") or {}

    return {
        "code":         a.get("ActivityCode", ""),
        "name":         a.get("ActivityName", "").strip(),
        "matnas":       institute.get("InstituteName", "").strip(),
        "matnas_code":  institute.get("InstituteCode", ""),
        "category":     category.get("CategoryName", "").strip(),
        "scope":        scope.get("ScopeName", "").strip(),
        "sub_category": sub.get("CategoryName", "").strip(),
        "instructor":   a.get("InstructorName", "").strip(),
        "start":        fmt_date(a.get("StartDate", "")),
        "end":          fmt_date(a.get("EndDate", "")),
        "days":         fmt_times(a.get("WeeklyTimes") or []),
        "audience":     fmt_audience(a.get("AudienceTargets") or []),
        "price":        a.get("Price", ""),
        "available":    a.get("AvailablePlaces", ""),
        "total":        a.get("TotalAvailablePlaces", ""),
        "online_reg":   a.get("InternetRegister", False),
        "details":      (a.get("Details") or "").strip()[:200],
    }


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------

def matches(activity: dict, matnas: str | None, category: str | None,
            scope: str | None, available_only: bool) -> bool:
    if available_only:
        av = activity.get("available")
        if av is not None and av <= 0:
            return False
    if matnas:
        kw = matnas.lower()
        if kw not in activity["matnas"].lower():
            return False
    if category:
        kw = category.lower()
        if kw not in activity["name"].lower() and kw not in activity["category"].lower():
            return False
    if scope:
        kw = scope.lower()
        if kw not in activity["scope"].lower():
            return False
    return True


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def compute_diff(old: list[dict], new: list[dict]) -> dict:
    """
    Compare two full snapshots (unfiltered) keyed by activity code.
    Returns a dict with keys: added, removed, changed.
    Each 'changed' entry lists the fields that differ with old/new values.
    """
    old_by_code = {a["code"]: a for a in old if a.get("code")}
    new_by_code = {a["code"]: a for a in new if a.get("code")}

    old_codes = set(old_by_code)
    new_codes = set(new_by_code)

    added   = [new_by_code[c] for c in sorted(new_codes - old_codes)]
    removed = [old_by_code[c] for c in sorted(old_codes - new_codes)]

    changed = []
    for code in sorted(old_codes & new_codes):
        o, n = old_by_code[code], new_by_code[code]
        field_diffs = {}
        for field in DIFF_FIELDS:
            ov, nv = o.get(field), n.get(field)
            if ov != nv:
                field_diffs[field] = {"old": ov, "new": nv}
        if field_diffs:
            changed.append({"code": code, "name": n["name"], "matnas": n["matnas"], "changes": field_diffs})

    return {"added": added, "removed": removed, "changed": changed}


def print_diff(diff: dict):
    added, removed, changed = diff["added"], diff["removed"], diff["changed"]

    if not added and not removed and not changed:
        print("\nNo changes since last snapshot.")
        return

    if added:
        print(f"\n+++ {len(added)} NEW activities +++")
        for a in added:
            pr = f"{a['price']:.0f}₪" if isinstance(a["price"], (int, float)) else str(a["price"])
            print(f"  + [{a['matnas']}] {a['name']}  ({pr}, {a.get('available','-')} spots)")

    if removed:
        print(f"\n--- {len(removed)} REMOVED activities ---")
        for a in removed:
            print(f"  - [{a['matnas']}] {a['name']}")

    if changed:
        print(f"\n~~ {len(changed)} CHANGED activities ~~")
        for c in changed:
            print(f"  ~ [{c['matnas']}] {c['name']}")
            for field, vals in c["changes"].items():
                print(f"      {field}: {vals['old']} → {vals['new']}")

    print(f"\nSummary: +{len(added)} added  -{len(removed)} removed  ~{len(changed)} changed")


def save_diff(diff: dict, path: Path):
    path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved diff: {path}")


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def load_snapshot() -> list[dict] | None:
    if SNAPSHOT_FILE.exists():
        data = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
        return data.get("activities")
    return None


def save_snapshot(activities: list[dict], ts: str):
    SNAPSHOT_FILE.write_text(
        json.dumps({"captured_at": ts, "activities": activities}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Also keep a timestamped archive copy
    archive = OUT_DIR / f"snapshot_{ts}.json"
    archive.write_text(SNAPSHOT_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Snapshot saved: {SNAPSHOT_FILE.name}  (archive: {archive.name})")


# ---------------------------------------------------------------------------
# Print / save
# ---------------------------------------------------------------------------

def print_table(activities: list[dict]):
    if not activities:
        print("No activities found.")
        return

    header = (
        f"{'#':<4} {'שם שיעור':<40} {'מתנס':<22} {'קטגוריה':<18} "
        f"{'ימים ושעות':<30} {'קהל':<18} {'מחיר':>8} {'מקומות':>9}"
    )
    print("\n" + header)
    print("-" * len(header))

    for i, a in enumerate(activities, 1):
        av = str(a["available"]) if a["available"] != "" else "-"
        pr = f"{a['price']:.0f}₪" if isinstance(a["price"], (int, float)) else str(a["price"])
        print(
            f"{i:<4} {a['name'][:39]:<40} {a['matnas'][:21]:<22} "
            f"{a['category'][:17]:<18} {a['days'][:29]:<30} "
            f"{a['audience'][:17]:<18} {pr:>8} {av:>9}"
        )

    print(f"\nTotal: {len(activities)} activities")


def save_json(activities: list[dict], path: Path):
    path.write_text(json.dumps(activities, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved JSON: {path}")


FIELDS_CSV = [
    "code", "name", "matnas", "category", "scope", "sub_category",
    "instructor", "start", "end", "days", "audience",
    "price", "available", "total", "online_reg", "details",
]


def save_csv(activities: list[dict], path: Path):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS_CSV, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(activities)
    print(f"Saved CSV:  {path}")


# ---------------------------------------------------------------------------
# List helpers
# ---------------------------------------------------------------------------

def list_centers(raw_data: dict):
    institutes = raw_data.get("Institutes") or []
    print("\nAll community centers (מתנסים):")
    for inst in sorted(institutes, key=lambda x: x.get("InstituteName", "")):
        print(f"  [{inst.get('InstituteCode','')}] {inst.get('InstituteName','')}")


def list_categories(raw_data: dict):
    cats   = raw_data.get("Categories") or []
    scopes = raw_data.get("Scopes") or []
    print("\nActivity scopes (תחומים):")
    for s in sorted(scopes, key=lambda x: x.get("ScopeName", "")):
        print(f"  [{s.get('ScopeCode','')}] {s.get('ScopeName','')}")
    print("\nActivity categories (קטגוריות):")
    for c in sorted(cats, key=lambda x: x.get("CategoryName", "")):
        print(f"  [{c.get('CategoryCode','')}] {c.get('CategoryName','')}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(args: argparse.Namespace):
    print("Fetching activities from Tel Aviv municipality API...")
    raw = await fetch_data()

    if args.list_centers:
        list_centers(raw)
        return

    if args.list_categories:
        list_categories(raw)
        return

    raw_activities = raw.get("Activities") or []
    print(f"Fetched {len(raw_activities)} activities total.")

    # Full normalised list (unfiltered) — used for snapshots and diff
    all_activities = [normalise(a) for a in raw_activities]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUT_DIR.mkdir(exist_ok=True)

    # --- Diff mode ---
    if args.diff:
        old_snapshot = load_snapshot()
        if old_snapshot is None:
            print("No previous snapshot found — saving first snapshot now.")
        else:
            diff = compute_diff(old_snapshot, all_activities)
            print_diff(diff)
            save_diff(diff, OUT_DIR / f"diff_{ts}.json")
        save_snapshot(all_activities, ts)
        return

    # --- Normal mode ---
    filtered = [
        a for a in all_activities
        if matches(a, args.matnas, args.category, args.scope, args.available)
    ]

    print_table(filtered)

    if args.output == "none":
        return

    if args.output in ("json", "both"):
        save_json(filtered, OUT_DIR / f"matnas_{ts}.json")
    if args.output in ("csv", "both"):
        save_csv(filtered, OUT_DIR / f"matnas_{ts}.csv")


def cli():
    parser = argparse.ArgumentParser(
        description="Search classes at Tel Aviv community centers (מתנסים)"
    )
    parser.add_argument("--matnas", "-m",
        help="Filter by center name (partial match), e.g. 'רמת אביב'")
    parser.add_argument("--category", "-c",
        help="Filter by activity name or category keyword, e.g. 'יוגה'")
    parser.add_argument("--scope", "-s",
        help="Filter by scope keyword, e.g. 'ספורט'")
    parser.add_argument("--available", "-a", action="store_true",
        help="Show only activities with available spots")
    parser.add_argument("--output", "-o",
        choices=["json", "csv", "both", "none"], default="both",
        help="Output format (default: both)")
    parser.add_argument("--diff", "-d", action="store_true",
        help=(
            "Compare current data against the last saved snapshot, "
            "print what changed, then save a new snapshot. "
            "Ignores --matnas/--category filters (always diffs the full dataset)."
        ))
    parser.add_argument("--list-centers", action="store_true",
        help="Print all community center names and exit")
    parser.add_argument("--list-categories", action="store_true",
        help="Print all category/scope names and exit")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main(cli()))
