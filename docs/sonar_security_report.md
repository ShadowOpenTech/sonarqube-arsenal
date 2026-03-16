# sonar_security_report.py

Generates a comprehensive security report across **all projects, all branches, and all pull requests** in your SonarQube instance.

## What it fetches

- **Vulnerabilities** — total count + breakdown by status and severity
- **Security Hotspots** — total count + breakdown by status (To Review, Acknowledged, Fixed, Safe)
- **Project summary** — branch count, PR count, last scan date

## Requirements

```bash
pip install httpx openpyxl python-dotenv
```

> `python-dotenv` is optional but recommended — it allows the script to auto-load a `.env` file from the project root so you don't need to pass credentials as CLI arguments. If not installed, the script falls back to system environment variables.

## Usage

```bash
python sonar_security_report.py \
    --url      http://sonarqube.example.com \
    --username admin \
    --password secret
```

### All options

| Flag | Default | Description |
|------|---------|-------------|
| `--url` | *(required)* | SonarQube base URL |
| `--username` | *(required)* | Username for basic auth |
| `--password` | *(required)* | Password for basic auth |
| `--output` | `sonar_report.json` | JSON output file path |
| `--excel` | `sonar_report.xlsx` | Excel output file path |
| `--concurrency` | `10` | Max parallel API requests |
| `--limit` | `0` (all) | Process only the first N projects — useful for test runs against large instances |
| `--summary-only` | off | Print summary table only, skip per-branch detail |
| `--no-verify-ssl` | off | Disable SSL verification (for self-signed certs) |

## Output

### Console

- A **summary table** — one row per project with totals and last scan date
- A **detailed tree** — per project → per branch/PR → vuln and hotspot counts by status/severity

### JSON (`sonar_report.json`)

Full structured dump of all projects, branches, PRs, and their security counts.

### Excel (`sonar_report.xlsx`)

Three formatted sheets:

**Sheet 1 — Summary**
One row per project. Grand total row at the bottom.

**Sheet 2 — Branches**
One row per project+branch. Columns are grouped into two bands:
- **Vulnerabilities** — total, by status
- **Security Hotspots** — total, by status

**Sheet 3 — Pull Requests**
Same layout as Branches, with additional PR metadata (title, source → target branch).
Only created if at least one project has PR-based analysis configured.

> Rows with vulnerabilities or hotspots are highlighted in orange. Vuln status columns are dynamic — built from whatever statuses SonarQube returns, so the sheet stays accurate across SonarQube version upgrades.

## Notes

- Uses **basic auth**. A SonarQube user token can be passed as `--username` with `--password` left empty.
- Branches and PRs are fetched via separate API endpoints and counted independently.
- Parallel execution is on by default. Tune `--concurrency` down if you hit rate limits on large instances.
- Projects without PR analysis configured are handled gracefully — no errors, PR count shows 0.
