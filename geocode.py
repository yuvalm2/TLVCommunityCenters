#!/usr/bin/env python3
"""
Refine matnas center coordinates using Nominatim (OpenStreetMap geocoder).
Run once to improve accuracy of the map markers in the web UI.

Usage:
    python geocode.py

Reads locations.json, geocodes any entry that looks imprecise or is missing,
and writes the improved results back.  Nominatim allows 1 request/sec.
"""

import asyncio
import json
from pathlib import Path

import aiohttp

API_URL = (
    "https://www.tel-aviv.gov.il"
    "/_vti_bin/TlvSP2013PublicSite/TlvListUtils.svc/GetActivities/false/"
)
NOMINATIM = "https://nominatim.openstreetmap.org/search"
LOC_FILE  = Path(__file__).parent / "locations.json"
UA        = "matnas-scraper/1.0 (github matnas-scraper)"


async def fetch_institutes(session: aiohttp.ClientSession) -> list[dict]:
    headers = {"Accept": "application/json", "User-Agent": UA}
    async with session.get(API_URL, headers=headers, ssl=False) as r:
        text = await r.text()
        data = json.loads(text)
        if isinstance(data, str):
            data = json.loads(data)
        return data.get("Institutes") or []


async def geocode(session: aiohttp.ClientSession, name: str) -> dict | None:
    queries = [
        f"{name}, תל אביב יפו, ישראל",
        f"{name}, Tel Aviv-Yafo, Israel",
    ]
    for q in queries:
        params = {"q": q, "format": "json", "limit": 1, "countrycodes": "il"}
        async with session.get(NOMINATIM, params=params,
                               headers={"User-Agent": UA}) as r:
            results = await r.json(content_type=None)
        if results:
            return {"lat": float(results[0]["lat"]),
                    "lng": float(results[0]["lon"]),
                    "display": results[0].get("display_name", "")}
        await asyncio.sleep(1.1)
    return None


async def main():
    existing: dict = {}
    if LOC_FILE.exists():
        existing = json.loads(LOC_FILE.read_text(encoding="utf-8"))

    async with aiohttp.ClientSession() as session:
        print("Fetching institute list from Tel Aviv API…")
        institutes = await fetch_institutes(session)
        print(f"Found {len(institutes)} institutes.\n")

        results: dict = dict(existing)
        updated = 0

        for inst in institutes:
            code = str(inst.get("InstituteCode", ""))
            name = (inst.get("InstituteName") or "").strip()
            if not name or not code:
                continue

            prev = results.get(code, {})
            # Skip if already geocoded via Nominatim (has 'display' field)
            if prev.get("display"):
                print(f"  [skip]  {name}")
                continue

            print(f"  Geocoding: {name} … ", end="", flush=True)
            loc = await geocode(session, name)
            await asyncio.sleep(1.1)   # Nominatim rate-limit

            if loc:
                results[code] = {"name": name, "code": code, **loc}
                print(f"✓  ({loc['lat']:.4f}, {loc['lng']:.4f})")
            else:
                # Keep existing coordinates as fallback
                if code in results:
                    print("✗  (keeping existing coordinates)")
                else:
                    results[code] = {"name": name, "code": code,
                                     "lat": 32.0800, "lng": 34.7800,
                                     "unknown": True}
                    print("✗  (city center fallback)")

            updated += 1
            LOC_FILE.write_text(
                json.dumps(results, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    found = sum(1 for v in results.values() if not v.get("unknown"))
    print(f"\nDone. {found}/{len(results)} centers located. Saved → {LOC_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
