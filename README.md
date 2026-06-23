# Matnas Scraper — Tel Aviv Community Center Classes

Fetches all classes and activities from all Tel Aviv municipality community centers (מתנסים) directly from the municipality's internal API. No browser required.

**Data source:** `www5.tel-aviv.gov.il/TlvCommunity/activities/activities-list`  
**API endpoint (discovered via network interception):**
```
https://www.tel-aviv.gov.il/_vti_bin/TlvSP2013PublicSite/TlvListUtils.svc/GetActivities/false/
```

Returns ~2,200+ activities across 45 community centers.

---

## Setup

```bash
cd c:\code\matnas-scraper
pip install -r requirements.txt
```

**Requirements:** Python 3.10+, `aiohttp`, `flask`, `playwright` (playwright is only needed if you ever re-run the network discovery; the scraper itself uses aiohttp directly).

---

## Web UI

Interactive timetable view with text search — no command line needed.

```bash
python app.py
# → open http://localhost:5000
```

Features:
- **Sidebar** — list of all 45 community centers with activity counts; click to select
- **Timetable view** — visual weekly grid (Sun–Fri), activities positioned by time with overlap handling
- **List view** — toggle to a card-per-day layout
- **Map view** — click "🗺 מפה" in the topbar to see all centers on an interactive map; marker size = number of activities; click a marker → select that center and view its timetable
- **Search bar** — real-time text search across all centers simultaneously (name, instructor, category, details)
- **Activity detail** — click any card for full info (price, spots, schedule, description)
- Data is cached for 1 hour; restart the server or wait to refresh

The server runs on `0.0.0.0:5000` — accessible from other machines on your network too.

### Map coordinates

Approximate coordinates for all 45 centers are stored in `locations.json` (pre-populated).
To improve accuracy using OpenStreetMap geocoding (run once, takes ~60 seconds):

```bash
python geocode.py
```

This updates `locations.json` in-place and can be re-run safely — already-geocoded centers are skipped.

---

## Data source — live API, not website scraping

The data comes directly from the Tel Aviv municipality's internal API:
```
https://www.tel-aviv.gov.il/_vti_bin/TlvSP2013PublicSite/TlvListUtils.svc/GetActivities/false/
```

This is the **same backend** used by `www5.tel-aviv.gov.il/TlvCommunity/activities/activities-list`.
- The response is always live (available spots, current prices, active courses)
- No need to "re-scrape" on a schedule — just reload the web UI or restart `app.py`
- The web app caches data in memory for 1 hour automatically

**When to use `--diff` (weekly automation):**
Between seasons (September, February) or mid-season, the municipality adds/removes courses and changes prices.
Running `python scraper.py --diff` weekly captures these changes:
- New courses added
- Courses that ended or were cancelled
- Price changes
- Instructor changes

---

## Usage

### Basic queries

```bash
# All activities — print table + save JSON and CSV to output/
python scraper.py

# Filter by center name (partial match, Hebrew)
python scraper.py --matnas "פלורנטין"
python scraper.py --matnas "רמת אביב"
python scraper.py --matnas "בבלי"

# Filter by activity name or category keyword
python scraper.py --category "יוגה"
python scraper.py --category "שחייה"
python scraper.py --category "ג'ודו"

# Filter by scope (broader grouping)
python scraper.py --scope "ספורט"
python scraper.py --scope "מחול"

# Show only activities that still have open spots
python scraper.py --available

# Combine filters freely
python scraper.py --matnas "פלורנטין" --category "קפוארה" --available
```

### Output format

```bash
python scraper.py --output json   # JSON only
python scraper.py --output csv    # CSV only  (opens in Excel)
python scraper.py --output both   # both (default)
python scraper.py --output none   # print only, don't save files
```

Output files land in `output/` with a timestamp, e.g.:
```
output/matnas_20260613_234406.json
output/matnas_20260613_234406.csv
```

### Discovery helpers

```bash
# List all 45 community centers with their codes
python scraper.py --list-centers

# List all activity scopes and categories
python scraper.py --list-categories
```

---

## Weekly change tracking (`--diff`)

Running with `--diff` fetches the full dataset, compares it against the last saved snapshot, prints a change report, and saves a new snapshot. Use this for weekly automation.

```bash
python scraper.py --diff
```

**First run** — no previous snapshot exists yet, so it just saves the baseline:
```
Fetching activities from Tel Aviv municipality API...
Fetched 2263 activities total.
No previous snapshot found — saving first snapshot now.
Snapshot saved: snapshot_latest.json  (archive: snapshot_20260613_234406.json)
```

**Subsequent runs** — shows what changed:
```
+++ 3 NEW activities +++
  + [פלורנטין] קורס בישול ערבי  (350₪, 12 spots)
  + [בבלי] פילאטיס בוקר ב  (200₪, 8 spots)
  ...

--- 1 REMOVED activities ---
  - [מגיד] יוגה מתקדמים

~~ 14 CHANGED activities ~~
  ~ [רמת אביב] קונדיטוריה גמלאים
      available: 10 → 3
  ~ [פלורנטין] קפוארה מבוגרים
      price: 250.0 → 300.0
  ...

Summary: +3 added  -1 removed  ~14 changed
```

**Output files:**
```
output/snapshot_latest.json        ← always the most recent full snapshot
output/snapshot_20260620_080000.json  ← timestamped archive of every snapshot
output/diff_20260620_080000.json   ← machine-readable diff report
```

The diff tracks these fields per activity: `name`, `matnas`, `category`, `price`, `available`, `total`, `days`, `instructor`.

---

## Automating weekly runs (Windows Task Scheduler)

### Option A — Task Scheduler GUI

1. Open **Task Scheduler** → *Create Basic Task*
2. Name: `Matnas Weekly Diff`
3. Trigger: Weekly, pick a day/time (e.g. Monday 08:00)
4. Action: *Start a program*
   - Program: `python`
   - Arguments: `C:\code\matnas-scraper\scraper.py --diff`
   - Start in: `C:\code\matnas-scraper`
5. Finish. The diff report lands in `output/` each week.

### Option B — Task Scheduler via PowerShell (one-time setup)

```powershell
$action  = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "C:\code\matnas-scraper\scraper.py --diff" `
    -WorkingDirectory "C:\code\matnas-scraper"

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "08:00"

Register-ScheduledTask `
    -TaskName "Matnas Weekly Diff" `
    -Action $action `
    -Trigger $trigger `
    -RunLevel Highest
```

To verify it's registered:
```powershell
Get-ScheduledTask -TaskName "Matnas Weekly Diff"
```

To run it immediately (test):
```powershell
Start-ScheduledTask -TaskName "Matnas Weekly Diff"
```

To remove it:
```powershell
Unregister-ScheduledTask -TaskName "Matnas Weekly Diff" -Confirm:$false
```

### Redirect output to a log file

If you want to keep a log of each run, change the Arguments field to:
```
C:\code\matnas-scraper\scraper.py --diff >> C:\code\matnas-scraper\output\run.log 2>&1
```

Or in PowerShell wrap it:
```powershell
$action = New-ScheduledTaskAction `
    -Execute "powershell" `
    -Argument "-Command `"cd C:\code\matnas-scraper; python scraper.py --diff >> output\run.log 2>&1`""
```

---

## Output file reference

| File | Created by | Contents |
|---|---|---|
| `output/matnas_<ts>.json` | normal run | filtered activity list |
| `output/matnas_<ts>.csv` | normal run | same, as CSV (Excel-friendly, UTF-8 BOM) |
| `output/snapshot_latest.json` | `--diff` | full unfiltered snapshot, always overwritten |
| `output/snapshot_<ts>.json` | `--diff` | timestamped archive of each snapshot |
| `output/diff_<ts>.json` | `--diff` | machine-readable change report |

### Diff JSON structure

```json
{
  "added": [ { ...activity fields... } ],
  "removed": [ { ...activity fields... } ],
  "changed": [
    {
      "code": "RA15202600458",
      "name": "קונדיטוריה גמלאים",
      "matnas": "מרכז קהילתי רמת אביב",
      "changes": {
        "available": { "old": 10, "new": 3 },
        "price":     { "old": 285.0, "new": 300.0 }
      }
    }
  ]
}
```

---

## Future / TODO

### Herzliya Enzo community center

[Enzo](https://herzliya.smarticket.co.il/אנזו_-_המקום_לצעירים_בהרצליה) is a Herzliya community center that uses the **smarticket.co.il** platform — a completely different system from the Tel Aviv municipality API. Support is deferred until after summer 2026 when activities resume (~September). Will require a separate scraper.

---

## Activity fields reference

| Field | Description |
|---|---|
| `code` | Unique activity code (e.g. `RA15202600458`) — stable across weeks |
| `name` | Activity name in Hebrew |
| `matnas` | Community center name |
| `matnas_code` | Community center numeric code |
| `category` | Activity category (e.g. `התעמלות וכושר`, `מחול ותנועה`) |
| `scope` | Broader scope (e.g. `ספורט ופעילות גופנית`) |
| `sub_category` | Sub-category if present |
| `instructor` | Instructor name |
| `start` / `end` | Season start/end dates (YYYY-MM-DD) |
| `days` | Schedule, e.g. `יום ב' 17:00-18:00 \| יום ה' 17:00-18:00` |
| `audience` | Target age group(s) |
| `price` | Price in NIS |
| `available` | Available spots right now |
| `total` | Total capacity |
| `online_reg` | `true` if online registration is open |
| `details` | Free-text description (first 200 chars) |
