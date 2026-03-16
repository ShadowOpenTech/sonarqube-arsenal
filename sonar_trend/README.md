# SonarQube Trend Suite

A three-script workflow for tracking SonarQube security metrics over time across a large project portfolio.

---

## Overview

```
sonar_branch_select.py          (one-time / periodic)
        │
        └─► branch_selection.json   ──►  sonar_trend_snapshot.py  (cron / CI)
                                                 │
                                                 └─► snapshots/snapshot_*.json
                                                              │
                                            dept_mapping.csv  │
                                                         ▼    ▼
                                              sonar_trend_report.py  (on-demand)
                                                         │
                                                         └─► trend_report.xlsx
```

| Script | Role | When to run |
|---|---|---|
| `sonar_branch_select.py` | Evaluates all projects and picks the best representative branch per project | Once, then whenever the branch landscape changes |
| `sonar_trend_snapshot.py` | Reads the branch cache and collects security metrics, saves a timestamped JSON | Daily or weekly (cron / CI) |
| `sonar_trend_report.py` | Reads N most-recent snapshots + dept mapping, produces an Excel trend report | On demand |

---

## Prerequisites

```bash
pip install httpx openpyxl tqdm python-dotenv
```

Tested with Python 3.11+.

A `.env` file in the working directory is auto-loaded if `python-dotenv` is installed:

```
SONAR_URL=http://sonarqube.example.com
SONAR_USERNAME=admin
SONAR_PASSWORD=secret
SONAR_BRANCH_CACHE=branch_selection.json
SONAR_SNAPSHOTS_DIR=snapshots
SONAR_DEPT_MAPPING=dept_mapping.csv
```

---

## dept_mapping.csv format

The department mapping file has exactly four columns (case-sensitive headers):

| Column | Description |
|---|---|
| `CODE` | Project code prefix — the part before the first `_` in a project name (e.g. `PAYMENTS` from `PAYMENTS_backend-service`) |
| `DEPT` | Human-readable department name used to group projects in the report |
| `internetFacing` | `true` / `false` — whether projects with this code are internet-facing |
| `Critical` | `true` / `false` — whether projects with this code are business-critical |

Example (`dept_mapping.example.csv`):

```
CODE,DEPT,internetFacing,Critical
PAYMENTS,Finance,true,true
AUTH,Finance,true,true
INVENTORY,Operations,false,true
HRMS,HR,false,false
REPORTING,Operations,false,false
```

---

## Script 1 — sonar_branch_select.py

### Purpose

Fetches all SonarQube projects, evaluates their branches, and selects the single best representative branch per project.  Results are saved to `branch_selection.json` and an Excel report.

### Branch selection priority

For each project, the script tries in order:

1. **isMain branch** — if LOC > 0 (verified via `/api/measures/component`)
2. **Named fallbacks** — `develop`, `development`, `dev`, `master` — first with LOC > 0
3. **Any scanned branch** (has `analysisDate`) with LOC > 0, most recently scanned first
4. **None** — project is marked Inactive

A selected branch is **stale** if its `analysisDate` is more than 60 days ago.  It is still selected, but `is_stale: true` is recorded.

If a `branch_selection.json` already exists at `--output`, the script loads it and records `previous_branch` and `branch_changed_at` for any project whose branch changed.

### Reason codes

| Code | Meaning |
|---|---|
| `isMain-valid` | isMain branch with LOC > 0, not stale |
| `isMain-stale` | isMain branch with LOC > 0, but > 60 days old |
| `fallback-develop` | `develop` branch selected as fallback |
| `fallback-development` | `development` branch selected as fallback |
| `fallback-dev` | `dev` branch selected as fallback |
| `fallback-master` | `master` branch selected as fallback |
| `any-recent` | Most recently scanned non-fallback branch, not stale |
| `any-stale` | Most recently scanned non-fallback branch, > 60 days old |
| `none` | No valid branch found — project is Inactive |

### Usage

```bash
python sonar_branch_select.py \
    --url http://sonarqube.example.com \
    --username admin \
    --password secret

# Custom paths, higher concurrency
python sonar_branch_select.py \
    --url http://sonar.internal \
    --username admin --password secret \
    --output branch_selection.json \
    --excel  branch_selection_report.xlsx \
    --concurrency 20

# Skip SSL verification
python sonar_branch_select.py ... --no-verify-ssl
```

### CLI options

| Option | Env var | Default | Description |
|---|---|---|---|
| `--url` | `SONAR_URL` | — | SonarQube base URL |
| `--username` | `SONAR_USERNAME` | — | SonarQube username |
| `--password` | `SONAR_PASSWORD` | — | SonarQube password |
| `--output` | `SONAR_BRANCH_CACHE` | `branch_selection.json` | JSON output path |
| `--excel` | `SONAR_BRANCH_EXCEL` | `branch_selection_report.xlsx` | Excel output path |
| `--concurrency` | `SONAR_CONCURRENCY` | `10` | Max parallel API requests |
| `--no-verify-ssl` | — | off | Disable SSL certificate verification |

### Excel sheets

| Sheet | Contents |
|---|---|
| Summary | Stats table (totals, valid, fallback, stale, inactive) |
| Valid | All projects with a branch selected; rows colour-coded by reason |
| Inactive | Projects with no valid branch |

Row colours in the Valid sheet:

- Green — `isMain-valid`
- Yellow — fallback or `any-recent`
- Orange — stale (`isMain-stale`, `any-stale`)

---

## Script 2 — sonar_trend_snapshot.py

### Purpose

Periodic script that reads `branch_selection.json`, collects security metrics for each active project using its selected branch, and saves a timestamped snapshot JSON file.

### Flow

1. Load branch cache (`branch_selection.json`).  Warn if missing or older than 30 days.
2. Optionally filter to a list of project keys (`--projects`).
3. For each active project (branch != null):
   - **1 API call** for vulnerability data (facets: statuses, OWASP Top 10 2021, SonarQube security categories)
   - **4 concurrent API calls** for hotspot counts (TO_REVIEW, ACKNOWLEDGED, FIXED, SAFE)
   - On error: record the error message and continue (best-effort)
4. Save snapshot to `<snapshots-dir>/snapshot_YYYYMMDD_HHMMSS.json`
5. Prune oldest snapshots keeping only the most recent `--retain` files

If any projects fail, the snapshot `status` is set to `"partial"` instead of `"complete"`.

### Usage

```bash
python sonar_trend_snapshot.py \
    --url http://sonarqube.example.com \
    --username admin \
    --password secret

# Scope to specific projects
python sonar_trend_snapshot.py \
    --url http://sonarqube.example.com \
    --username admin --password secret \
    --projects project_keys.txt

# Custom dirs, keep 12 snapshots (quarterly rolling window)
python sonar_trend_snapshot.py \
    --url http://sonar.internal \
    --username admin --password secret \
    --cache   branch_selection.json \
    --snapshots-dir snapshots \
    --retain 12
```

### CLI options

| Option | Env var | Default | Description |
|---|---|---|---|
| `--url` | `SONAR_URL` | — | SonarQube base URL |
| `--username` | `SONAR_USERNAME` | — | SonarQube username |
| `--password` | `SONAR_PASSWORD` | — | SonarQube password |
| `--cache` | `SONAR_BRANCH_CACHE` | `branch_selection.json` | Branch cache JSON path |
| `--projects` | `SONAR_PROJECTS_FILE` | none (all) | Text file with project keys to scope |
| `--snapshots-dir` | `SONAR_SNAPSHOTS_DIR` | `snapshots` | Directory to write snapshot files |
| `--retain` | `SONAR_SNAPSHOTS_RETAIN` | `52` | How many snapshots to keep |
| `--concurrency` | `SONAR_CONCURRENCY` | `10` | Max parallel API requests |
| `--no-verify-ssl` | — | off | Disable SSL certificate verification |

### Snapshot JSON structure (abbreviated)

```json
{
  "snapshot_id": "20260317_100000",
  "generated_at": "2026-03-17T10:00:00+00:00",
  "sonar_url": "http://...",
  "branch_cache_file": "branch_selection.json",
  "branch_cache_generated_at": "...",
  "branch_cache_age_days": 5,
  "projects_in_scope": 500,
  "projects_success": 498,
  "projects_failed": 2,
  "projects_skipped": 10,
  "status": "complete",
  "projects": [
    {
      "key": "PAYMENTS_backend-service",
      "name": "PAYMENTS_backend-service",
      "code": "PAYMENTS",
      "branch": "develop",
      "branch_analysis_date": "2026-03-15T08:22:00+00:00",
      "branch_age_days": 2,
      "branch_changed": false,
      "vulnerabilities": {
        "active": 42,
        "acknowledged": 6,
        "by_status": {"OPEN": 30, "CONFIRMED": 12, "FALSE_POSITIVE": 4, "ACCEPTED": 2},
        "by_owasp": {"a03:2021-injection": 5},
        "by_sonarqube": {"sql-injection": 5, "xss": 12}
      },
      "hotspots": {
        "to_review": 8, "acknowledged": 2, "fixed": 5, "safe": 1, "total": 16
      },
      "error": null
    }
  ]
}
```

---

## Script 3 — sonar_trend_report.py

### Purpose

On-demand report generator.  Reads the N most recent snapshots and the department mapping CSV, then produces a multi-sheet Excel workbook with trend charts.

No SonarQube API calls are made — only local files are read.

### Usage

```bash
python sonar_trend_report.py \
    --mapping dept_mapping.csv

# Last 12 snapshots, internet-facing and critical projects only
python sonar_trend_report.py \
    --mapping dept_mapping.csv \
    --snapshots-count 12 \
    --internet-facing-only \
    --critical-only \
    --output trend_report_ic.xlsx

# Custom snapshots directory
python sonar_trend_report.py \
    --mapping dept_mapping.csv \
    --snapshots-dir /data/sonar/snapshots \
    --output /reports/trend_report.xlsx
```

### CLI options

| Option | Env var | Default | Description |
|---|---|---|---|
| `--snapshots-dir` | `SONAR_SNAPSHOTS_DIR` | `snapshots` | Directory containing snapshot JSON files |
| `--mapping` | `SONAR_DEPT_MAPPING` | required | Path to department mapping CSV |
| `--output` | `SONAR_TREND_OUTPUT` | `trend_report.xlsx` | Excel output path |
| `--projects` | `SONAR_PROJECTS_FILE` | none (all) | Text file with project keys to restrict |
| `--snapshots-count` | `SONAR_SNAPSHOTS_COUNT` | `52` | Number of most-recent snapshots to load |
| `--internet-facing-only` | — | off | Only include projects with `internetFacing=true` |
| `--critical-only` | — | off | Only include projects with `Critical=true` |

### Excel sheet structure

| Sheet | Contents |
|---|---|
| **Overview** | Report metadata, snapshot range, counts |
| **Fleet Trend** | Active vulns, acknowledged vulns, to-review hotspots, and net active delta over time; line chart |
| **Dept - \<Name\>** | Active vulns aggregated by CODE within the department over time; line chart; one sheet per dept |
| **Code - \<Name\>** | Active vulns per individual project within a CODE over time; line chart; one sheet per CODE |
| **Events** | Branch changes, project additions/removals, unmapped codes, stale branches, partial snapshots |
| **Coverage Gaps** | Section 1 — inactive projects (no valid branch); Section 2 — unmapped codes |

**Chart notes:**
- Charts use `openpyxl.chart.LineChart` with `chart.style = 10`
- Chart dimensions: 30 wide × 15 tall (EMU units via openpyxl defaults)
- For Dept and Code sheets, only the top 20 series by latest-snapshot value are charted to avoid illegibility

**Colour coding in Dept sheets:**
- Light red row — CODE is marked `Critical=true`
- Light yellow row — CODE is marked `internetFacing=true`

**Colour coding in Events sheet:**

| Event type | Colour |
|---|---|
| Branch Changed | Blue |
| Project Added | Green |
| Project Removed | Orange |
| Unmapped Code | Yellow |
| Branch Stale | Light orange |
| Snapshot Partial | Light orange |

---

## Operational notes

- **60-day staleness threshold** — a branch whose last `analysisDate` is more than 60 days ago is flagged as stale.  It is still selected but marked `is_stale: true` in the cache and highlighted in reports.
- **30-day cache age warning** — `sonar_trend_snapshot.py` warns if `branch_selection.json` is more than 30 days old.  Re-run `sonar_branch_select.py` to refresh it.
- **Best-effort snapshots** — if individual projects fail during a snapshot run, they are recorded with `error: <message>` and the snapshot `status` is set to `"partial"`.  Subsequent runs will retry those projects.
- **Branch change events** — `sonar_trend_snapshot.py` detects branch changes by comparing the current selected branch against `previous_branch` in the cache entry.  The report surfaces these in the Events sheet.
- **internetFacing / Critical filtering** — pass `--internet-facing-only` and/or `--critical-only` to `sonar_trend_report.py` to scope the Excel output to the highest-priority subset of your portfolio.
- **Snapshot retention** — snapshots are pruned to the most recent `--retain` files after each successful run.  The default of 52 corresponds to one year of weekly snapshots.
