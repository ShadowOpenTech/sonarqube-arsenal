# sonar_reopen_vulnerabilities.py

Reopens all non-OPEN, non-CLOSED vulnerabilities across a list of projects and all their branches.

## What it does

For each project key provided, the script:
1. Fetches all branches
2. Scans every branch for vulnerabilities that are not `OPEN` or `CLOSED`
3. Transitions each issue back to `OPEN` using the appropriate API transition

| Previous Status  | Transition applied |
|------------------|--------------------|
| `CONFIRMED`      | `unconfirm`        |
| `FALSE_POSITIVE` | `reopen`           |
| `ACCEPTED`       | `reopen`           |
| `FIXED`          | `reopen`           |

`CLOSED` issues are always skipped — they are auto-managed by the scanner when the underlying code is fixed and cannot be manually reopened. `OPEN` issues are not queried at all.

## Requirements

```bash
pip install httpx openpyxl tqdm python-dotenv
```

A user account with **Administer Issues** permission on each target project is required.

## Input

A plain text file with one project key per line. Blank lines and lines starting with `#` are ignored.

```
# projects.txt
my-org:backend-service
my-org:frontend-app
com.example:payments-api
```

## Usage

```bash
# Dry run — see what would be reopened without making any changes
python sonar_reopen_vulnerabilities.py \
    --url http://sonarqube.example.com \
    --username admin \
    --password secret \
    --projects projects.txt \
    --dry-run

# Run for real
python sonar_reopen_vulnerabilities.py \
    --url http://sonarqube.example.com \
    --username admin \
    --password secret \
    --projects projects.txt
```

### All options

| Flag | Default | Description |
|------|---------|-------------|
| `--url` | *(required)* | SonarQube base URL |
| `--username` | *(required)* | SonarQube username |
| `--password` | *(required)* | SonarQube password |
| `--projects` | `projects.txt` | Path to project keys file |
| `--output` | `reopen_report.xlsx` | Excel report output path |
| `--concurrency` | `10` | Max parallel API requests |
| `--dry-run` | off | Scan and report without making any changes |
| `--no-verify-ssl` | off | Disable SSL verification (for self-signed certs) |

All options can also be set via environment variables or a `.env` file — see `.env.example`.

## Output

### Console

Progress bars for each phase, followed by a summary:

```
  REOPEN SUMMARY
════════════════════════════════════════════════════════════
  Total processed  : 312
  Transitioned     : 308
  Failed           : 4
  Dry run          : 0
════════════════════════════════════════════════════════════
```

### Excel (`reopen_report.xlsx`)

**Sheet 1 — Summary**
One row per project+branch with counts of transitioned, failed, and dry-run issues. Grand total row at the bottom.

**Sheet 2 — Detail**
One row per issue with full context:

| Column | Description |
|--------|-------------|
| Project Key | SonarQube project key |
| Project Name | Display name |
| Branch | Branch the issue belongs to |
| Issue Key | SonarQube issue key |
| Component | File/component path |
| Message | Issue message |
| Severity | Issue severity |
| Previous Status | Status before reopening |
| Transition Applied | API transition used |
| Outcome | `transitioned` / `failed` / `dry_run` |
| Error | Error message if the transition failed |

Rows are colour-coded: **green** = transitioned, **orange** = failed, **blue** = dry run.

## Notes

- SonarQube caps issue pagination at **10,000 results** per query. If a project branch has more than 10,000 matching issues a warning is logged and only the first 10,000 are processed.
- Always run with `--dry-run` first on production instances to review the scope before committing changes.
- External issues (imported from third-party tools) cannot be transitioned via this API and will appear as failures.
