#!/usr/bin/env python3
"""
scraper_ctgoodjobs.py — collect job ads from CTgoodjobs.hk

What it does
============
1. Walks the paginated IT job listing
   (https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=N)
   via CTgoodjobs' private JSON API and pulls the summary card for every job.
2. Fetches the full HTML description for each NEW job via the job-detail
   endpoint.  Jobs whose IDs were already fetched in a previous run (tracked
   in fetched_job_ids.txt) are skipped entirely — they are not included in
   the output.
3. Saves the result to CSV and/or JSON.
4. Optionally uploads JSON output to Cloudflare R2.

Incremental scraping
====================
The file ``fetched_job_ids.txt`` (one ID per line) records every job whose
detail has been successfully fetched.  On subsequent runs, jobs already
present in that file are **skipped** — they won't appear in the output at all.
This avoids re-fetching and keeps the daily output containing only new jobs.

R2 upload
=========
With ``--upload-r2``, the JSON output is uploaded to:
    <R2_BUCKET>/<r2-prefix>/<YYYY-MM-DD>.json
e.g.  my-bucket/ctgoodjobs/2025-06-15.json

The fetched_job_ids.txt is also synced to R2 on every run
(download before, upload after).

Usage
-----
    # default: 1 page of IT jobs
    python scraper_ctgoodjobs.py

    # 20 pages, upload to R2
    python scraper_ctgoodjobs.py --pages 20 --upload-r2

    # Custom category
    python scraper_ctgoodjobs.py \
        --url https://jobs.ctgoodjobs.hk/jobs/jobs-in-banking-finance?page=1 \
        --pages 3 --output banking_jobs

    # limit detail fetches (useful for testing)
    python scraper_ctgoodjobs.py --max-jobs 5

Dependencies
------------
    pip install requests boto3
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests

# ── Local imports ────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from r2_uploader import load_dotenv, upload_to_r2, download_from_r2


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

CATEGORIES: dict[str, dict[str, str]] = {
    "information-technology": {
        "jobcatareaId": "021",
        "name": "Information Technology",
    },
    "banking-finance": {
        "jobcatareaId": "010",
        "name": "Banking / Finance",
    },
    "sales-cs-business-devpt": {
        "jobcatareaId": "018",
        "name": "Sales, CS & Business Devpt",
    },
}

SEARCH_URL = "https://api01.ctgoodjobs.hk/job/api/jobs/search"
DETAIL_URL = "https://api01.ctgoodjobs.hk/job/api/jobDetail/ct/detail"
PAGE_SIZE = 30
DEFAULT_CHANNEL_ID = "001"
DEFAULT_LANG = "en-US"

# Data directory for persistent state
DATA_DIR = _SCRIPT_DIR / "scraper_data" / "ctgoodjobs"
FETCHED_IDS_FILE = DATA_DIR / "fetched_job_ids.txt"

# R2 folder prefix
R2_PREFIX = "ctgoodjobs"


# --------------------------------------------------------------------------- #
# Fetched-job-ID tracking
# --------------------------------------------------------------------------- #

def load_fetched_ids(path: Path = FETCHED_IDS_FILE) -> set[str]:
    """Read previously-fetched job IDs from file.  Returns an empty set on miss."""
    if not path.exists():
        return set()
    with open(path, "r", encoding="utf-8") as fh:
        return {line.strip() for line in fh if line.strip()}


def save_fetched_ids(ids: set[str], path: Path = FETCHED_IDS_FILE) -> None:
    """Write the full set of fetched job IDs to file (one per line)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for job_id in sorted(ids):
            fh.write(job_id + "\n")
    print(f"  [ids] Saved {len(ids)} fetched IDs to {path}", file=sys.stderr)


def sync_fetched_ids_from_r2(
    path: Path = FETCHED_IDS_FILE, r2_prefix: str = R2_PREFIX
) -> None:
    """Download fetched_job_ids.txt from R2 if it exists (so state persists across machines)."""
    try:
        r2_key = f"{r2_prefix}/fetched_job_ids.txt"
        download_from_r2(r2_key, str(path))
    except Exception as exc:
        print(f"  [R2] Could not sync fetched IDs from R2: {exc}", file=sys.stderr)


def sync_fetched_ids_to_r2(
    path: Path = FETCHED_IDS_FILE, r2_prefix: str = R2_PREFIX
) -> None:
    """Upload fetched_job_ids.txt to R2 after a run."""
    if not path.exists():
        return
    try:
        r2_key = f"{r2_prefix}/fetched_job_ids.txt"
        upload_to_r2(str(path), r2_key)
    except Exception as exc:
        print(f"  [R2] Could not sync fetched IDs to R2: {exc}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def make_visitor_id() -> str:
    return "v" + time.strftime("%Y%m%d%H%M%S", time.gmtime()) + str(random.randint(10**8, 10**9 - 1))


def make_sid() -> str:
    return str(random.randint(10**8, 10**9 - 1))


def build_headers(visitor_id: str, sid: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "channel-id": DEFAULT_CHANNEL_ID,
        "visitor-id": visitor_id,
        "sid": sid,
        "lang": DEFAULT_LANG,
        "user-id": "",
        "login": "false",
        "Origin": "https://jobs.ctgoodjobs.hk",
        "Referer": "https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=1",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
    }


def build_search_body(
    *,
    jobcatarea_id: str,
    page: int,
    page_size: int = PAGE_SIZE,
) -> dict[str, Any]:
    return {
        "pagingInputs": {
            "page": str(page),
            "pageSize": str(page_size),
            "pageOneSize": str(page_size),
        },
        "sort": 2,
        "searchTypeId": "Y",
        "jobcatareaIds": [jobcatarea_id],
    }


def category_from_url(url: str) -> tuple[str, str]:
    path = urlparse(url).path
    m = re.match(r"^/jobs/jobs-in-([a-z0-9-]+)$", path)
    if not m:
        raise ValueError(f"Cannot derive category slug from URL: {url!r}")
    slug = m.group(1)
    if slug not in CATEGORIES:
        raise KeyError(
            f"Unknown category slug {slug!r}.  Known slugs: {sorted(CATEGORIES)}"
        )
    return slug, CATEGORIES[slug]["jobcatareaId"]


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #

@dataclass
class JobSummary:
    job_id: str
    job_title: str
    job_url: str
    company_id: str
    company_name: str
    company_url: str
    company_logo: str
    publish_display: str
    publish_date: str
    valid_through_date: str
    experience: str
    salary: str
    employment_types: str
    career_levels: str
    highlights: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "JobSummary":
        def _display(d: dict | None) -> str:
            return (d or {}).get("display", "")

        return cls(
            job_id=raw.get("jobId", ""),
            job_title=raw.get("jobTitle", ""),
            job_url=raw.get("url", ""),
            company_id=raw.get("companyId", ""),
            company_name=raw.get("companyName", ""),
            company_url=raw.get("companyUrl", ""),
            company_logo=raw.get("image", "") or raw.get("imageBak", ""),
            publish_display=_display(raw.get("publishTime")),
            publish_date=(raw.get("publishTime") or {}).get("date", ""),
            valid_through_date=(raw.get("validThrough") or {}).get("date", ""),
            experience=(
                f"{(raw.get('experience') or {}).get('from', '')}-"
                f"{(raw.get('experience') or {}).get('to', '')} yrs"
            ),
            salary=(raw.get("salary") or {}).get("salaryValue", "") or "N/A",
            employment_types=", ".join(
                et.get("name", "") for et in (raw.get("empTypes") or [])
            ),
            career_levels=", ".join(
                cl.get("name", "") for cl in (raw.get("careerLevels") or [])
            ),
            highlights=list(raw.get("highlights") or []),
        )


@dataclass
class JobDetail:
    description_html: str
    company_description_html: str
    apply_url: str
    job_areas: list[dict[str, str]]
    skills: list[dict[str, str]]

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "JobDetail":
        job = (raw.get("job") or {})
        job_info = (raw.get("jobInfo") or {})
        return cls(
            description_html=job.get("content", "") or "",
            company_description_html=job.get("companyDesc", "") or "",
            apply_url=job.get("applyUrl", "") or "",
            job_areas=list(job_info.get("jobareas") or []),
            skills=list(raw.get("skills") or []),
        )


# --------------------------------------------------------------------------- #
# API client
# --------------------------------------------------------------------------- #

class CTGoodJobsClient:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self.session = requests.Session()
        self.timeout = timeout
        self.visitor_id = make_visitor_id()
        self.sid = make_sid()

    def _headers(self) -> dict[str, str]:
        return build_headers(self.visitor_id, self.sid)

    def search(
        self,
        jobcatarea_id: str,
        page: int = 1,
        page_size: int = PAGE_SIZE,
    ) -> dict[str, Any]:
        body = build_search_body(
            jobcatarea_id=jobcatarea_id,
            page=page,
            page_size=page_size,
        )
        r = self.session.post(
            SEARCH_URL, headers=self._headers(), data=json.dumps(body),
            timeout=self.timeout,
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("statusCode") != 1:
            raise RuntimeError(
                f"Search returned statusCode={payload.get('statusCode')!r}, "
                f"error={payload.get('error')!r}"
            )
        return payload["data"]

    def iter_jobs(
        self,
        jobcatarea_id: str,
        max_pages: int,
        *,
        delay_seconds: float = 1.0,
    ) -> Iterable[JobSummary]:
        """Yield JobSummary for every job across ``max_pages`` pages."""
        for page in range(1, max_pages + 1):
            data = self.search(jobcatarea_id, page=page)
            jobs = data.get("jobs") or []
            if not jobs:
                print(
                    f"  page {page}: 0 jobs (total reported: "
                    f"{data.get('total', 0)}) — stopping.",
                    file=sys.stderr,
                )
                break
            print(
                f"  page {page}: {len(jobs)} jobs "
                f"(total reported: {data.get('total', 0)})",
                file=sys.stderr,
            )
            for raw in jobs:
                yield JobSummary.from_api(raw)
            if delay_seconds:
                time.sleep(delay_seconds)

    def job_detail(self, job_id: str) -> JobDetail:
        params = {"jobId": str(job_id)}
        r = self.session.get(
            DETAIL_URL, headers=self._headers(), params=params, timeout=self.timeout,
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("statusCode") != 1:
            raise RuntimeError(
                f"Detail returned statusCode={payload.get('statusCode')!r}, "
                f"error={payload.get('error')!r}"
            )
        return JobDetail.from_api(payload["data"])


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #

CSV_FIELDS = [
    "job_id", "job_title", "job_url", "company_id", "company_name", "company_url",
    "company_logo", "publish_display", "publish_date", "valid_through_date",
    "experience", "salary", "employment_types", "career_levels",
    "highlights", "description_html", "company_description_html", "apply_url",
    "job_areas", "skills",
]


def write_json(records: list[dict[str, Any]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)


def write_csv(records: list[dict[str, Any]], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            row = dict(r)
            for key in ("highlights", "job_areas", "skills"):
                if isinstance(row.get(key), list):
                    row[key] = json.dumps(row[key], ensure_ascii=False)
            writer.writerow(row)


# --------------------------------------------------------------------------- #
# Main scrape logic
# --------------------------------------------------------------------------- #

def _empty_detail() -> dict[str, Any]:
    """Return empty detail fields for jobs where detail fetch failed."""
    return {
        "description_html": "",
        "company_description_html": "",
        "apply_url": "",
        "job_areas": [],
        "skills": [],
    }


def scrape(
    *,
    url: str,
    max_pages: int,
    delay: float,
    max_jobs: int = 0,
) -> list[dict[str, Any]]:
    slug, jobcatarea_id = category_from_url(url)
    print(
        f"Scraping category {slug!r} (jobcatareaId={jobcatarea_id}), "
        f"max_pages={max_pages}",
        file=sys.stderr,
    )

    # Load previously-fetched IDs — jobs in this list are skipped entirely
    fetched_ids: set[str] = load_fetched_ids()
    new_fetched_ids: set[str] = set()
    print(f"  [ids] {len(fetched_ids)} previously-fetched IDs loaded", file=sys.stderr)

    client = CTGoodJobsClient()
    records: list[dict[str, Any]] = []
    detail_fetched = 0
    detail_skipped = 0
    detail_failed = 0
    jobs_seen = 0

    for job in client.iter_jobs(
        jobcatarea_id, max_pages=max_pages, delay_seconds=delay,
    ):
        jobs_seen += 1

        # Skip previously-fetched jobs entirely
        if job.job_id in fetched_ids:
            detail_skipped += 1
            continue

        rec = asdict(job)

        # Fetch detail for every new job
        try:
            detail = client.job_detail(job.job_id)
            rec.update({
                "description_html": detail.description_html,
                "company_description_html": detail.company_description_html,
                "apply_url": detail.apply_url,
                "job_areas": [a for a in detail.job_areas],
                "skills": [s for s in detail.skills],
            })
            new_fetched_ids.add(job.job_id)
            detail_fetched += 1
        except Exception as exc:
            print(
                f"  ! detail failed for {job.job_id} ({job.job_title!r}): {exc}",
                file=sys.stderr,
            )
            rec.update(_empty_detail())
            detail_failed += 1
        if delay:
            time.sleep(delay)

        records.append(rec)

        # Stop once the max-jobs quota is reached
        if max_jobs > 0 and detail_fetched >= max_jobs:
            print(f"  [quota] Reached max-jobs limit ({max_jobs}). Stopping.", file=sys.stderr)
            break

    # Save updated fetched IDs
    if new_fetched_ids:
        all_ids = fetched_ids | new_fetched_ids
        save_fetched_ids(all_ids)

    print(
        f"  [ids] {jobs_seen} jobs seen, {detail_skipped} skipped (already fetched), "
        f"{detail_fetched} detail fetched, {detail_failed} failed",
        file=sys.stderr,
    )

    return records


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> int:
    load_dotenv()

    p = argparse.ArgumentParser(
        description="Scrape job ads from jobs.ctgoodjobs.hk",
    )
    p.add_argument(
        "--url",
        default="https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=1",
        help="A listing URL on jobs.ctgoodjobs.hk (used to derive the category).",
    )
    p.add_argument(
        "--pages", type=int, default=1,
        help="How many listing pages to walk (default: 1, page size is 30).",
    )
    p.add_argument(
        "--output", default="ctgoodjobs_jobs",
        help="Output file prefix (default: ctgoodjobs_jobs). Writes .csv and .json.",
    )
    p.add_argument(
        "--format", choices=("csv", "json", "both"), default="json",
        help="Output format (default: both).",
    )
    p.add_argument(
        "--delay", type=float, default=1.0,
        help="Seconds to sleep between requests (default: 1.0).",
    )
    p.add_argument(
        "--upload-r2", action="store_true",
        help="Upload JSON output to Cloudflare R2 (requires .env with R2 credentials).",
    )
    p.add_argument(
        "--max-jobs", type=int, default=0,
        help="Max number of detail pages to fetch (0 = unlimited). Useful for testing.",
    )
    p.add_argument(
        "--r2-prefix", default=R2_PREFIX,
        help=f"R2 folder prefix (default: {R2_PREFIX}). Use 'testing/ctgoodjobs' for test runs.",
    )
    args = p.parse_args()

    # Sync fetched IDs from R2 before scraping
    if args.upload_r2:
        sync_fetched_ids_from_r2(r2_prefix=args.r2_prefix)

    records = scrape(
        url=args.url,
        max_pages=args.pages,
        delay=args.delay,
        max_jobs=args.max_jobs,
    )

    if not records:
        print("No new jobs collected.", file=sys.stderr)
        return 1

    # Local save
    if args.format in ("json", "both"):
        write_json(records, f"{DATA_DIR}/{args.output}.json")
        print(f"Wrote {len(records)} records to {args.output}.json", file=sys.stderr)
    if args.format in ("csv", "both"):
        write_csv(records, f"{DATA_DIR}/{args.output}.csv")
        print(f"Wrote {len(records)} records to {args.output}.csv", file=sys.stderr)

    # R2 upload
    if args.upload_r2:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        json_path = f"{args.output}.json"
        r2_key = f"{args.r2_prefix}/{today}.json"
        try:
            upload_to_r2(json_path, r2_key)
            print(f"  ✓ Uploaded to R2: {r2_key}", file=sys.stderr)
        except Exception as exc:
            print(f"  ✗ R2 upload failed: {exc}", file=sys.stderr)

        # Sync fetched IDs back to R2
        sync_fetched_ids_to_r2(r2_prefix=args.r2_prefix)

    return 0


if __name__ == "__main__":
    sys.exit(main())
