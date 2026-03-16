# SonarQube Arsenal

Scripts and tools to automate, report, and get the most out of SonarQube's security capabilities.

A growing collection of standalone automation and reporting scripts for [SonarQube](https://www.sonarsource.com/products/sonarqube/). Built with **2025.1 LTA Enterprise Edition** in mind, but most scripts work with recent versions.

---

## Scripts

| Script | Description | Docs |
|--------|-------------|------|
| [`sonar_security_report.py`](sonar_security_report.py) | Fetch vulnerabilities & security hotspots across all projects, branches, and PRs. Outputs to console, JSON, and Excel. | [docs](docs/sonar_security_report.md) |
| [`sonar_reopen_vulnerabilities.py`](sonar_reopen_vulnerabilities.py) | Reopen all non-OPEN, non-CLOSED vulnerabilities across a list of projects and all their branches. Supports dry-run mode. Outputs an Excel report. | [docs](docs/sonar_reopen_vulnerabilities.md) |

---

## Contributing

Have a script that helps with SonarQube automation or reporting? PRs are welcome.
