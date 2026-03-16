# sonar_propagate_status.py

Propagates acknowledged issue statuses from a source branch to matching OPEN issues on all other active branches of the same project(s).

## What it does

For each project, the script:
1. Identifies the source branch (default: `isMain`, override with `--source-branch`)
2. Fetches all acknowledged issues from the source branch
3. For each active target branch, fetches all `OPEN` issues
4. Matches issues across branches by `(rule, component, hash)`
5. Applies the corresponding transition to matched issues on the target

| Source status | Transition applied | Result |
|---|---|---|
| `CONFIRMED` | `confirm` | Target issue becomes CONFIRMED |
| `FALSE_POSITIVE` | `falsepositive` | Target issue becomes FALSE_POSITIVE |
| `ACCEPTED` | `accept` | Target issue becomes ACCEPTED |

Target issues that already carry any non-`OPEN` status are left untouched — their status was a deliberate choice on that branch.

Branches with no `analysisDate` or last scanned more than 60 days ago are silently skipped.

## Requirements

```bash
pip install httpx openpyxl tqdm python-dotenv
```

A user account with **Administer Issues** permission on each target project is required.

## Input

A single project key (`--project`), a text file of project keys (`--projects`), or both — keys are merged and deduplicated.

```
# projects.txt
my-org:backend-service
my-org:frontend-app
```

## Usage

```bash
# Dry run on a single project
python sonar_propagate_status.py \
    --url http://sonarqube.example.com \
    --username admin \
    --password secret \
    --project my-org:backend-service \
    --dry-run

# Run for real on a list of projects
python sonar_propagate_status.py \
    --url http://sonarqube.example.com \
    --username admin \
    --password secret \
    --projects projects.txt

# Use a specific source branch instead of isMain
python sonar_propagate_status.py \
    --url http://sonarqube.example.com \
    --username admin \
    --password secret \
    --project my-org:backend-service \
    --source-branch develop
```

### All options

| Flag | Env var | Default | Description |
|---|---|---|---|
| `--url` | `SONAR_URL` | *(required)* | SonarQube base URL |
| `--username` | `SONAR_USERNAME` | *(required)* | SonarQube username |
| `--password` | `SONAR_PASSWORD` | *(required)* | SonarQube password |
| `--project` | `SONAR_PROJECT` | none | Single project key (comma-separated for multiple) |
| `--projects` | `SONAR_PROJECTS_FILE` | none | Text file with project keys, one per line |
| `--source-branch` | `SONAR_SOURCE_BRANCH` | isMain (auto) | Branch to read statuses from |
| `--output` | `SONAR_PROPAGATE_OUTPUT` | `propagate_report.xlsx` | Excel report output path |
| `--concurrency` | `SONAR_CONCURRENCY` | `10` | Max parallel API requests |
| `--dry-run` | — | off | Scan and report without applying any transitions |
| `--no-verify-ssl` | — | off | Disable SSL verification (self-signed certs) |

All options can also be set via environment variables or a `.env` file — see `.env.example`.

## Output

### Console

Progress bars for each phase, followed by a summary:

```
  PROPAGATION SUMMARY
════════════════════════════════════════════════════════════
  Total matched    : 47
  Synced           : 44
  Failed           : 3
  Dry run          : 0
════════════════════════════════════════════════════════════
```

### Excel (`propagate_report.xlsx`)

**Sheet 1 — Summary**
One row per project + target branch with counts of synced, failed, and dry-run issues. Grand total row at the bottom.

**Sheet 2 — Detail**
One row per matched issue:

| Column | Description |
|---|---|
| Project Key | SonarQube project key |
| Project Name | Display name |
| Source Branch | Branch the status was read from |
| Target Branch | Branch the transition was applied to |
| Issue Key | SonarQube issue key |
| Component | File/component path |
| Rule | Rule key that raised the issue |
| Message | Issue message |
| Source Status | Status on the source branch |
| Transition Applied | API transition used |
| Outcome | `synced` / `failed` / `dry_run` |
| Error | Error message if the transition failed |

Rows are colour-coded: **green** = synced, **orange** = failed, **blue** = dry run.

## Notes

- SonarQube caps issue pagination at **10,000 results** per query. If a branch has more than 10,000 acknowledged issues a warning is logged and only the first 10,000 are considered for matching.
- Issues without a `hash` field (line fingerprint) are excluded from matching — they cannot be reliably identified across branches.
- Always run with `--dry-run` first on production instances to review the scope before committing changes.
- Both `--project` and `--projects` can be specified simultaneously; keys are merged and deduplicated.
