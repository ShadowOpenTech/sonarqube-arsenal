# SonarQube Arsenal

Scripts and tools to automate, report, and get the most out of SonarQube's security capabilities.

This repository is a growing collection of automation and reporting scripts for [SonarQube](https://www.sonarsource.com/products/sonarqube/). Each script is standalone and targets a specific use case — from bulk security reporting to workflow automation. Built with SonarQube **2025.1 LTA Enterprise Edition** in mind, but most scripts work with recent versions.

---

## Scripts

### `sonar_security_report.py`

Generates a comprehensive security report across **all projects, all branches, and all pull requests** in your SonarQube instance.

**What it fetches:**
- Vulnerabilities — total count + breakdown by **status** and **severity**
- Security Hotspots — total count + breakdown by **status** (To Review, Acknowledged, Fixed, Safe)
- Project-level summary — branch count, PR count, last scan date

**Output:**
| Format | Description |
|--------|-------------|
| Console | Summary table + detailed tree per project → branch/PR |
| JSON | Full structured data dump |
| Excel | 3 formatted sheets — Summary, Branches, Pull Requests |

#### Requirements

```bash
pip install httpx openpyxl
```

#### Usage

```bash
python sonar_security_report.py \
    --url      http://sonarqube.example.com \
    --username admin \
    --password secret
```

**All options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--url` | *(required)* | SonarQube base URL |
| `--username` | *(required)* | Username for basic auth |
| `--password` | *(required)* | Password for basic auth |
| `--output` | `sonar_report.json` | JSON output file path |
| `--excel` | `sonar_report.xlsx` | Excel output file path |
| `--concurrency` | `10` | Max parallel API requests |
| `--summary-only` | off | Print summary table only, skip per-branch detail |
| `--no-verify-ssl` | off | Disable SSL verification (for self-signed certs) |

#### Excel Report Structure

**Sheet 1 — Summary**
One row per project with totals and last scan date. Grand total row at the bottom.

**Sheet 2 — Branches**
One row per project+branch. Columns are grouped into two bands:
- **Vulnerabilities** — total, then per status, then per severity
- **Security Hotspots** — total, then per status

**Sheet 3 — Pull Requests**
Same layout as Branches, with additional PR metadata (title, source/target branch). Only created if any project has PR-based analysis.

> Rows with vulnerabilities or hotspots are highlighted in orange for quick scanning. Vuln status and severity columns are dynamic — built from whatever SonarQube actually returns.

---

## Notes

- All scripts use **basic auth** (username + password). Using a dedicated SonarQube token as the username with an empty password is also supported.
- Parallel execution is used by default to handle large instances with many projects and branches efficiently. Use `--concurrency` to tune if needed.
- PRs are fetched via a separate API endpoint (`/api/project_pull_requests/list`) and counted independently from branches.

---

## Contributing

Have a script that helps with SonarQube automation or reporting? PRs are welcome.
