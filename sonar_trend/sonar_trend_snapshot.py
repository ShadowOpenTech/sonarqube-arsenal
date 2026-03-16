#!/usr/bin/env python3
"""
SonarQube Trend Snapshot
========================
Periodic script (run daily/weekly via cron or CI) that reads branch_selection.json
and collects security metrics per project, saving a timestamped snapshot JSON.

For each project the selected branch is used (from the cache).  Inactive projects
(branch = null) are skipped and counted as "skipped".

Metrics collected per project (single API call for vulns, 4 concurrent calls for
hotspots — same pattern as sonar_security_report.py):
  - Vulnerability counts by status (OPEN, CONFIRMED, FALSE_POSITIVE, ACCEPTED)
  - Vulnerability breakdowns by OWASP Top 10 2021 and SonarQube security category
  - Hotspot counts: TO_REVIEW, ACKNOWLEDGED, FIXED, SAFE

On any per-project error the script records the error message and continues
(best-effort).  The snapshot status is set to "partial" if any project failed.

Snapshot files are saved as snapshot_YYYYMMDD_HHMMSS.json inside --snapshots-dir.
Old snapshots beyond --retain (default 52) are pruned automatically.

Usage:
    python sonar_trend_snapshot.py \\
        --url http://sonarqube.example.com \\
        --username admin \\
        --password secret

    # With explicit cache and output locations
    python sonar_trend_snapshot.py \\
        --url http://sonar.internal \\
        --username admin --password secret \\
        --cache branch_selection.json \\
        --snapshots-dir snapshots \\
        --retain 52

    # Snapshot only specific projects
    python sonar_trend_snapshot.py ... --projects project_keys.txt

    # Skip SSL verification (self-signed certs)
    python sonar_trend_snapshot.py ... --no-verify-ssl

Requirements:
    pip install httpx openpyxl tqdm python-dotenv
"""

import asyncio
import httpx
import json
import argparse
import sys
import os
from typing import Any, Optional
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from tqdm import tqdm
from tqdm.asyncio import tqdm as atqdm


# ── Constants ──────────────────────────────────────────────────────────────────

PAGE_SIZE           = 500
DEFAULT_CONCURRENCY = 10
DEFAULT_RETAIN      = 52
CACHE_AGE_WARN_DAYS = 30

HOTSPOT_STATUSES = ["TO_REVIEW", "ACKNOWLEDGED", "FIXED", "SAFE"]


# ── SonarQube Client ───────────────────────────────────────────────────────────

class SonarQubeClient:
    def __init__(self, base_url: str, username: str, password: str,
                 concurrency: int = DEFAULT_CONCURRENCY,
                 verify_ssl: bool = True):
        self.base_url   = base_url.rstrip("/")
        self.auth       = (username, password)
        self.verify_ssl = verify_ssl
        self._sem       = asyncio.Semaphore(concurrency)

    async def _get(self, client: httpx.AsyncClient, path: str,
                   params: dict[str, Any] | None = None) -> dict:
        async with self._sem:
            resp = await client.get(
                f"{self.base_url}{path}",
                params=params or {},
                auth=self.auth,
                timeout=60.0,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_vulnerability_data(
        self, client: httpx.AsyncClient,
        project_key: str, branch: str,
    ) -> dict:
        """One API call — uses facets to get status, OWASP and SonarQube category breakdown."""
        data = await self._get(client, "/api/issues/search", {
            "issueStatuses":           "OPEN,CONFIRMED,FALSE_POSITIVE,ACCEPTED",
            "facets":                  "statuses,owaspTop10-2021,sonarsourceSecurity",
            "impactSoftwareQualities": "SECURITY",
            "componentKeys":           project_key,
            "branch":                  branch,
            "ps":                      1,
        })

        by_status: dict[str, int]   = {}
        by_owasp: dict[str, int]    = {}
        by_sonarqube: dict[str, int] = {}

        for facet in data.get("facets", []):
            prop = facet.get("property", "")
            values = {v["val"]: v["count"] for v in facet.get("values", []) if v.get("count", 0) > 0}
            if prop == "statuses":
                by_status = values
            elif prop == "owaspTop10-2021":
                by_owasp = values
            elif prop == "sonarsourceSecurity":
                by_sonarqube = values

        active       = by_status.get("OPEN", 0) + by_status.get("CONFIRMED", 0)
        acknowledged = by_status.get("FALSE_POSITIVE", 0) + by_status.get("ACCEPTED", 0)

        return {
            "active":       active,
            "acknowledged": acknowledged,
            "by_status":    by_status,
            "by_owasp":     by_owasp,
            "by_sonarqube": by_sonarqube,
        }

    async def get_hotspot_data(
        self, client: httpx.AsyncClient,
        project_key: str, branch: str,
    ) -> dict:
        """4 concurrent calls — same pattern as sonar_security_report.py."""
        async def fetch_status(status: str) -> tuple[str, int]:
            params: dict[str, Any] = {
                "projectKey": project_key,
                "branch":     branch,
                "ps":         1,
            }
            if status == "TO_REVIEW":
                params["status"] = "TO_REVIEW"
            else:
                params["status"]     = "REVIEWED"
                params["resolution"] = status
            resp = await self._get(client, "/api/hotspots/search", params)
            return status, resp.get("paging", {}).get("total", 0)

        results = await asyncio.gather(
            *[fetch_status(s) for s in HOTSPOT_STATUSES],
            return_exceptions=True,
        )

        by_status: dict[str, int] = {}
        total = 0
        for i, res in enumerate(results):
            status = HOTSPOT_STATUSES[i]
            if isinstance(res, Exception):
                _warn(f"Hotspot fetch failed [{project_key}/{branch} status={status}]: {res}")
                by_status[status] = 0
            else:
                _, count = res
                by_status[status] = count
                total += count

        return {
            "to_review":    by_status.get("TO_REVIEW", 0),
            "acknowledged": by_status.get("ACKNOWLEDGED", 0),
            "fixed":        by_status.get("FIXED", 0),
            "safe":         by_status.get("SAFE", 0),
            "total":        total,
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _warn(msg: str) -> None:
    tqdm.write(f"  [WARN] {msg}", file=sys.stderr)


def _extract_code(name: str) -> str:
    return name.split("_")[0] if "_" in name else name


def _parse_iso(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _branch_age_days(analysis_date_iso: Optional[str]) -> Optional[int]:
    dt = _parse_iso(analysis_date_iso)
    if not dt:
        return None
    return (datetime.now(timezone.utc) - dt).days


def load_project_keys_file(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]


def load_branch_cache(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def prune_snapshots(snapshots_dir: Path, retain: int) -> None:
    files = sorted(snapshots_dir.glob("snapshot_*.json"))
    to_delete = files[:-retain] if len(files) > retain else []
    for f in to_delete:
        try:
            f.unlink()
        except OSError as exc:
            _warn(f"Could not delete old snapshot {f.name}: {exc}")


# ── Per-project collection ─────────────────────────────────────────────────────

async def collect_project(
    sonar: SonarQubeClient,
    client: httpx.AsyncClient,
    project_key: str,
    cache_entry: dict,
    pbar: tqdm,
) -> dict:
    """Collect metrics for one project.  Returns a project result dict."""
    branch = cache_entry.get("branch")
    analysis_date = cache_entry.get("analysis_date")
    previous_branch = cache_entry.get("previous_branch")
    branch_changed = (
        previous_branch is not None and branch != previous_branch
    )

    base = {
        "key":                project_key,
        "name":               cache_entry.get("name", project_key),
        "code":               cache_entry.get("code", _extract_code(project_key)),
        "branch":             branch,
        "branch_analysis_date": analysis_date,
        "branch_age_days":    _branch_age_days(analysis_date),
        "branch_changed":     branch_changed,
        "vulnerabilities":    None,
        "hotspots":           None,
        "error":              None,
    }

    try:
        vuln_data, hotspot_data = await asyncio.gather(
            sonar.get_vulnerability_data(client, project_key, branch),
            sonar.get_hotspot_data(client, project_key, branch),
        )
        base["vulnerabilities"] = vuln_data
        base["hotspots"]        = hotspot_data
    except Exception as exc:
        base["error"] = str(exc)
    finally:
        pbar.update(1)

    return base


# ── Orchestration ──────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    # ── Load cache ─────────────────────────────────────────────────────────────
    if not os.path.exists(args.cache):
        _warn(f"Branch cache file not found: {args.cache}")
        sys.exit(1)

    cache = load_branch_cache(args.cache)
    cache_projects: dict[str, dict] = cache.get("projects", {})
    cache_generated_at = cache.get("generated_at")

    cache_age_days: Optional[int] = None
    cache_dt = _parse_iso(cache_generated_at)
    if cache_dt:
        cache_age_days = (datetime.now(timezone.utc) - cache_dt).days
        if cache_age_days > CACHE_AGE_WARN_DAYS:
            _warn(f"Branch cache is {cache_age_days} days old "
                  f"(threshold: {CACHE_AGE_WARN_DAYS} days). "
                  f"Consider re-running sonar_branch_select.py.")

    # ── Resolve project scope ──────────────────────────────────────────────────
    if args.projects:
        requested_keys = load_project_keys_file(args.projects)
        project_keys: list[str] = []
        for key in requested_keys:
            if key in cache_projects:
                project_keys.append(key)
            else:
                _warn(f"Project key '{key}' not found in branch cache — skipping.")
    else:
        project_keys = list(cache_projects.keys())

    # Separate active and inactive (skipped)
    active_keys   = [k for k in project_keys if cache_projects[k].get("branch")]
    inactive_keys = [k for k in project_keys if not cache_projects[k].get("branch")]

    tqdm.write(f"\nProjects in scope  : {len(project_keys)}")
    tqdm.write(f"  Active (will scan): {len(active_keys)}")
    tqdm.write(f"  Skipped (inactive): {len(inactive_keys)}\n")

    sonar = SonarQubeClient(
        base_url=args.url,
        username=args.username,
        password=args.password,
        concurrency=args.concurrency,
        verify_ssl=not args.no_verify_ssl,
    )

    project_results: list[dict] = []

    async with httpx.AsyncClient(verify=not args.no_verify_ssl) as client:
        with tqdm(desc="Collecting metrics", unit="project",
                  total=len(active_keys)) as pbar:
            results: list[dict] = list(await asyncio.gather(*[
                collect_project(sonar, client, key, cache_projects[key], pbar)
                for key in active_keys
            ]))
        project_results.extend(results)

    # Add skipped entries
    for key in inactive_keys:
        entry = cache_projects[key]
        project_results.append({
            "key":                key,
            "name":               entry.get("name", key),
            "code":               entry.get("code", _extract_code(key)),
            "branch":             None,
            "branch_analysis_date": None,
            "branch_age_days":    None,
            "branch_changed":     False,
            "vulnerabilities":    None,
            "hotspots":           None,
            "error":              "skipped: no valid branch",
        })

    # ── Stats ──────────────────────────────────────────────────────────────────
    succeeded = sum(1 for r in project_results
                    if r["branch"] and r["error"] is None)
    failed    = sum(1 for r in project_results
                    if r["branch"] and r["error"] is not None
                    and not r["error"].startswith("skipped"))
    skipped   = len(inactive_keys)
    status    = "complete" if failed == 0 else "partial"

    # ── Build snapshot ─────────────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    snapshot_id = now.strftime("%Y%m%d_%H%M%S")

    snapshot = {
        "snapshot_id":              snapshot_id,
        "generated_at":             now.isoformat(),
        "sonar_url":                args.url,
        "branch_cache_file":        args.cache,
        "branch_cache_generated_at": cache_generated_at,
        "branch_cache_age_days":    cache_age_days,
        "projects_in_scope":        len(project_keys),
        "projects_success":         succeeded,
        "projects_failed":          failed,
        "projects_skipped":         skipped,
        "status":                   status,
        "projects":                 project_results,
    }

    # ── Save snapshot ──────────────────────────────────────────────────────────
    snapshots_dir = Path(args.snapshots_dir)
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = snapshots_dir / f"snapshot_{snapshot_id}.json"
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    # ── Prune old snapshots ────────────────────────────────────────────────────
    prune_snapshots(snapshots_dir, args.retain)

    # ── Console summary ────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  SNAPSHOT SUMMARY")
    print("═" * 60)
    print(f"  Snapshot ID      : {snapshot_id}")
    print(f"  Status           : {status.upper()}")
    print(f"  Projects in scope: {len(project_keys)}")
    print(f"  Succeeded        : {succeeded}")
    print(f"  Failed           : {failed}")
    print(f"  Skipped          : {skipped}")
    print(f"  Saved to         : {snapshot_path}")
    print("═" * 60)


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Collect SonarQube security metrics snapshot using branch cache.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--url",      default=os.getenv("SONAR_URL"),
                   help="SonarQube base URL  [env: SONAR_URL]")
    p.add_argument("--username", default=os.getenv("SONAR_USERNAME"),
                   help="SonarQube username  [env: SONAR_USERNAME]")
    p.add_argument("--password", default=os.getenv("SONAR_PASSWORD"),
                   help="SonarQube password  [env: SONAR_PASSWORD]")
    p.add_argument("--cache",    default=os.getenv("SONAR_BRANCH_CACHE", "branch_selection.json"),
                   help="Path to branch_selection.json  [env: SONAR_BRANCH_CACHE]")
    p.add_argument("--projects", default=os.getenv("SONAR_PROJECTS_FILE"),
                   help="Optional text file with project keys to scope the snapshot  "
                        "[env: SONAR_PROJECTS_FILE]")
    p.add_argument("--snapshots-dir", default=os.getenv("SONAR_SNAPSHOTS_DIR", "snapshots"),
                   help="Directory to write snapshot JSON files  [env: SONAR_SNAPSHOTS_DIR]")
    p.add_argument("--retain", type=int,
                   default=int(os.getenv("SONAR_SNAPSHOTS_RETAIN", DEFAULT_RETAIN)),
                   help="Number of most-recent snapshots to keep  [env: SONAR_SNAPSHOTS_RETAIN]")
    p.add_argument("--concurrency", type=int,
                   default=int(os.getenv("SONAR_CONCURRENCY", DEFAULT_CONCURRENCY)),
                   help="Max simultaneous API requests  [env: SONAR_CONCURRENCY]")
    p.add_argument("--no-verify-ssl", action="store_true",
                   help="Disable SSL certificate verification (self-signed certs)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    missing = [f"--{k}" for k, v in
               [("url", args.url), ("username", args.username),
                ("password", args.password)] if not v]
    if missing:
        print(f"Error: missing required values: {', '.join(missing)}\n"
              f"Pass them as CLI args or set SONAR_URL / SONAR_USERNAME / SONAR_PASSWORD "
              f"in your environment / .env file.",
              file=sys.stderr)
        sys.exit(1)

    print("SonarQube Trend Snapshot")
    print(f"  URL           : {args.url}")
    print(f"  Username      : {args.username}")
    print(f"  Branch cache  : {args.cache}")
    print(f"  Snapshots dir : {args.snapshots_dir}")
    print(f"  Retain        : {args.retain}")
    print(f"  Concurrency   : {args.concurrency}")
    print(f"  Verify SSL    : {not args.no_verify_ssl}")
    print()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
