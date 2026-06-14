#!/usr/bin/env python3
"""
Web UI for Tel Aviv matnas (community center) classes.
Serves a timetable view + text search at http://localhost:5000

Usage:
    python app.py
"""

import asyncio
import json
import time
from pathlib import Path
from flask import Flask, jsonify, render_template

LOCATIONS_FILE = Path(__file__).parent / "locations.json"

# ---- API ----
API_URL = (
    "https://www.tel-aviv.gov.il"
    "/_vti_bin/TlvSP2013PublicSite/TlvListUtils.svc/GetActivities/false/"
)
HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "he-IL,he;q=0.9",
    "Referer": "https://www5.tel-aviv.gov.il/TlvCommunity/activities/activities-list",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

# ---- CACHE (1 hour) ----
_cache: dict = {"data": None, "ts": 0.0}
CACHE_TTL = 3600


async def _fetch() -> dict:
    import aiohttp
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.get(API_URL, ssl=False) as r:
            r.raise_for_status()
            text = await r.text()
            data = json.loads(text)
            if isinstance(data, str):
                data = json.loads(data)
            return data


def _fmt_date(raw: str) -> str:
    from datetime import datetime
    if not raw:
        return ""
    if raw.startswith("/Date("):
        ms = int(raw[6:raw.index(")")])
        return datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d")
    return raw[:10]


def _parse_times(weekly: list) -> list[dict]:
    result = []
    for t in weekly:
        if isinstance(t, str):
            try:
                t = json.loads(t)
            except Exception:
                continue
        if not isinstance(t, dict):
            continue
        try:
            result.append({
                "day": int(t.get("dayIndex", 0)),
                "day_name": t.get("Value", ""),
                "from": t.get("new_from", ""),
                "to": t.get("new_to", ""),
            })
        except (ValueError, TypeError):
            continue
    return result


def _normalise(a: dict) -> dict:
    inst = a.get("Institute") or {}
    cat  = a.get("Category")  or {}
    scope = a.get("Scope")    or {}
    targets = a.get("AudienceTargets") or []
    audience = ", ".join(
        t.get("AudienceName", "") for t in targets if isinstance(t, dict)
    )
    return {
        "code":       a.get("ActivityCode", ""),
        "name":       (a.get("ActivityName") or "").strip(),
        "matnas":     (inst.get("InstituteName") or "").strip(),
        "matnas_code": inst.get("InstituteCode", ""),
        "category":   (cat.get("CategoryName") or "").strip(),
        "scope":      (scope.get("ScopeName") or "").strip(),
        "instructor": (a.get("InstructorName") or "").strip(),
        "start":      _fmt_date(a.get("StartDate", "")),
        "end":        _fmt_date(a.get("EndDate", "")),
        "times":      _parse_times(a.get("WeeklyTimes") or []),
        "audience":   audience,
        "price":      a.get("Price", ""),
        "available":  a.get("AvailablePlaces", ""),
        "total":      a.get("TotalAvailablePlaces", ""),
        "online_reg": bool(a.get("InternetRegister", False)),
        "details":    (a.get("Details") or "").strip()[:300],
    }


def get_activities() -> list[dict]:
    now = time.time()
    if _cache["data"] is None or now - _cache["ts"] > CACHE_TTL:
        raw = asyncio.run(_fetch())
        _cache["data"] = [_normalise(a) for a in (raw.get("Activities") or [])]
        _cache["ts"] = now
    return _cache["data"]


# ---- FLASK ----
app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/centers")
def centers():
    acts = get_activities()
    # Count activities per matnas code
    counts: dict[str, int] = {}
    for a in acts:
        code = a.get("matnas_code", "")
        if code:
            counts[code] = counts.get(code, 0) + 1

    locs: dict = {}
    if LOCATIONS_FILE.exists():
        locs = json.loads(LOCATIONS_FILE.read_text(encoding="utf-8"))

    result = []
    for code, loc in locs.items():
        result.append({
            "code":    code,
            "name":    loc["name"],
            "lat":     loc["lat"],
            "lng":     loc["lng"],
            "count":   counts.get(code, 0),
            "unknown": bool(loc.get("unknown")),
        })
    # Include any matnas from activities that are missing from locations file
    seen = {r["code"] for r in result}
    names_by_code: dict[str, str] = {}
    for a in acts:
        c = a.get("matnas_code", "")
        if c and c not in seen:
            names_by_code[c] = a.get("matnas", "")
    for code, name in names_by_code.items():
        result.append({"code": code, "name": name,
                       "lat": 32.08, "lng": 34.78,
                       "count": counts.get(code, 0), "unknown": True})

    return jsonify(result)


@app.route("/api/activities")
def activities():
    return jsonify(get_activities())


if __name__ == "__main__":
    print("Starting Tel Aviv Matnas web UI at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
