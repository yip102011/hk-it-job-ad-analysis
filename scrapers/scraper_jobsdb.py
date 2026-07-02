#!/usr/bin/env python3
"""
scraper_jobsdb.py — collect job ads from hk.jobsdb.com

What it does
============
1. Walks the paginated job listing on JobsDB Hong Kong
   (https://hk.jobsdb.com/jobs-in-information-communication-technology?page=N)
   via a headless Chromium browser (Playwright) and parses the rendered HTML.
2. Fetches the full job description from each NEW job's detail page.
   Jobs whose IDs were already fetched in a previous run (tracked in
   fetched_job_ids.txt) are skipped entirely — they are not included in
   the output.
3. Saves the result to CSV and/or JSON with **the same field schema as
   scraper_ctgoodjobs.py**, so output from both scrapers is directly
   comparable / mergeable.
4. Tracks fetched job IDs in fetched_job_ids.txt to support incremental
   scraping.
5. Optionally uploads JSON output to Cloudflare R2.

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
e.g.  my-bucket/jobsdb/2025-06-15.json

The fetched_job_ids.txt is also synced to R2 on every run
(download before, upload after).

Usage
-----
    # default: 1 page of ICT jobs
    python scraper_jobsdb.py

    # 2 pages
    python scraper_jobsdb.py --pages 2

    # 20 pages, upload to R2
    python scraper_jobsdb.py --pages 20 --upload-r2

    # page range
    python scraper_jobsdb.py --pages 1-5

    # Different category
    python scraper_jobsdb.py --category accounting

    # limit detail fetches (useful for testing)
    python scraper_jobsdb.py --max-jobs 5

Dependencies
------------
    pip install playwright boto3     # playwright for fetching, boto3 for --upload-r2
    playwright install chromium      # download the browser (one-time)
"""

from __future__ import annotations

import argparse
import csv
import html as html_module
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

# ── Local imports ────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from r2_uploader import load_dotenv, upload_to_r2, download_from_r2


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

BASE_URL = "https://hk.jobsdb.com"
DEFAULT_CATEGORY = "information-communication-technology"
DEFAULT_OUTPUT = "jobsdb_jobs"
REQUEST_DELAY = 2  # seconds between page fetches
DETAIL_DELAY = 2   # seconds between detail page fetches

# Data directory for persistent state
DATA_DIR = _SCRIPT_DIR / "scraper_data" / "jobsdb"
FETCHED_IDS_FILE = DATA_DIR / "fetched_job_ids.txt"

# R2 folder prefix
R2_PREFIX = "jobsdb"


# --------------------------------------------------------------------------- #
# Fetched-job-ID tracking
# --------------------------------------------------------------------------- #

def load_fetched_ids(path: Path = FETCHED_IDS_FILE) -> set[str]:
    """Read previously-fetched job IDs from file."""
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
    """Download fetched_job_ids.txt from R2 if it exists."""
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
# Data classes  (aligned with scraper_ctgoodjobs.py)
# --------------------------------------------------------------------------- #

@dataclass
class JobSummary:
    """A single job listing — same fields as ctgoodjobs_scraper.JobSummary."""

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


@dataclass
class JobDetail:
    """Full job detail — same fields as ctgoodjobs_scraper.JobDetail."""

    description_html: str
    company_description_html: str
    apply_url: str
    job_areas: list[dict[str, str]]
    skills: list[dict[str, str]]


# --------------------------------------------------------------------------- #
# HTML parser helpers  (regex on data-automation attributes)
# --------------------------------------------------------------------------- #

_RAW_FIELD_MAP = {
    "jobTitle": "title",
    "jobCompany": "company",
    "jobCardLocation": "location",
    "jobLocation": "location_alt",
    "jobSalary": "salary",
    "jobListingDate": "listing_date",
    "jobShortDescription": "description",
    "jobSubClassification": "sub_classification",
    "jobClassification": "classification",
}


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", "", text)
    return html_module.unescape(text).strip()


def _extract_field(card_html: str, automation: str) -> str:
    """Extract text content of a data-automation field from a job card chunk."""
    pattern = rf'data-automation="{automation}"[^>]*>(.*?)</(?:span|div|a|time)>'
    matches = re.findall(pattern, card_html, re.DOTALL | re.IGNORECASE)
    if matches:
        return _strip_tags(matches[0])
    return ""


def _extract_job_url(card_html: str) -> str:
    """Extract the first /job/ID href from a job card chunk."""
    pattern = r'href="(/job/\d+[^"]*)"'
    matches = re.findall(pattern, card_html)
    if matches:
        return html_module.unescape(matches[0])
    return ""


def _extract_job_id(url: str) -> str:
    """Pull the numeric job ID from a JobsDB job URL like /job/92715811?..."""
    m = re.search(r"/job/(\d+)", url)
    return m.group(1) if m else ""


def _parse_listing_date(raw: str) -> str:
    """
    Convert JobsDB listing date display (e.g. '16h ago', '3d ago')
    into an ISO date string if possible.  Falls back to the raw string.
    """
    now = datetime.now()
    m = re.match(r"(\d+)\s*h(?:ours?)?\s*ago", raw, re.IGNORECASE)
    if m:
        dt = now - timedelta(hours=int(m.group(1)))
        return dt.strftime("%Y-%m-%d")
    m = re.match(r"(\d+)\s*d(?:ays?)?\s*ago", raw, re.IGNORECASE)
    if m:
        dt = now - timedelta(days=int(m.group(1)))
        return dt.strftime("%Y-%m-%d")
    m = re.match(r"(\d+)\s*m(?:in(?:utes?)?)?\s*ago", raw, re.IGNORECASE)
    if m:
        dt = now - timedelta(minutes=int(m.group(1)))
        return dt.strftime("%Y-%m-%d")
    return raw


def parse_page(html: str) -> list[dict]:
    """
    Parse a JobsDB listing page HTML into a list of raw job dicts.
    Uses the 'normalJob' data-automation attribute to split into cards.
    """
    if not html:
        return []

    card_chunks = re.split(r'data-automation="normalJob"', html)
    raw_jobs: list[dict] = []

    for chunk in card_chunks[1:]:
        job: dict = {}

        for automation, key in _RAW_FIELD_MAP.items():
            value = _extract_field(chunk, automation)
            if value:
                if key == "location_alt":
                    if "location" not in job:
                        job["location"] = value
                else:
                    job[key] = value

        url = _extract_job_url(chunk)
        if url:
            job["url"] = url

        if job.get("title"):
            raw_jobs.append(job)

    return raw_jobs


def raw_to_job_summary(raw: dict) -> JobSummary:
    """Convert a raw parsed dict into a JobSummary aligned with ctgoodjobs schema."""

    job_url = raw.get("url", "")
    if job_url and job_url.startswith("/"):
        job_url = urljoin(BASE_URL, job_url)

    classification = raw.get("classification", "").strip("()").strip()
    sub_classification = raw.get("sub_classification", "")
    location = raw.get("location", "")
    listing_date = raw.get("listing_date", "")

    # Build highlights from available tags
    highlights: list[str] = []
    if classification:
        highlights.append(classification)
    if sub_classification and sub_classification != classification:
        highlights.append(sub_classification)
    if location:
        highlights.append(location)

    salary = raw.get("salary", "") or "N/A"

    return JobSummary(
        job_id=_extract_job_id(job_url),
        job_title=raw.get("title", ""),
        job_url=job_url,
        company_id="",                          # not available on listing page
        company_name=raw.get("company", ""),
        company_url="",                          # not available on listing page
        company_logo="",                         # not available on listing page
        publish_display=listing_date,            # e.g. "16h ago"
        publish_date=_parse_listing_date(listing_date) if listing_date else "",
        valid_through_date="",                   # not available on listing page
        experience="",                           # not available on listing page
        salary=salary,
        employment_types="",                     # may be filled from detail page
        career_levels="",                        # not available on listing page
        highlights=highlights,
    )


# --------------------------------------------------------------------------- #
# Detail page parsing
# --------------------------------------------------------------------------- #

def _extract_block(html: str, automation: str) -> str:
    """
    Extract the full inner HTML of a data-automation section.
    Uses a simple depth-counting approach to find the matching closing tag.
    """
    pattern = rf'<(\w+)[^>]*data-automation="{re.escape(automation)}"[^>]*>'
    m = re.search(pattern, html, re.IGNORECASE)
    if not m:
        return ""
    tag = m.group(1)
    start = m.end()

    # Find matching closing tag (simple depth counter)
    depth = 1
    pos = start
    max_pos = min(len(html), start + 100000)  # safety limit
    while pos < max_pos and depth > 0:
        open_match = re.search(rf"<{tag}[\s>]", html[pos:max_pos], re.IGNORECASE)
        close_match = re.search(rf"</{tag}\s*>", html[pos:max_pos], re.IGNORECASE)
        if close_match is None:
            break
        if open_match and open_match.start() < close_match.start():
            depth += 1
            pos += open_match.end()
        else:
            depth -= 1
            if depth == 0:
                return html[start:pos + close_match.start()]
            pos += close_match.end()
    return html[start:max_pos]


def _extract_detail_field(html: str, automation: str) -> str:
    """Extract text content of a data-automation field from the detail page."""
    pattern = rf'data-automation="{automation}"[^>]*>(.*?)</(?:span|div|a|time|p|li|h\d)>'
    matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
    if matches:
        return _strip_tags(matches[0])
    return ""


def parse_detail_page(html: str, job_url: str) -> JobDetail:
    """
    Parse a JobsDB job detail page HTML into a JobDetail.

    Key data-automation attributes on the detail page:
      - jobAdDetails: the full job description HTML
      - job-detail-work-type: employment type (e.g. "Full time")
      - job-detail-classifications: classification string
      - advertiser-name: company name
    """
    # Extract the full description HTML
    description_html = _extract_block(html, "jobAdDetails")

    # Extract work type / employment type
    work_type = _extract_detail_field(html, "job-detail-work-type")

    # Extract classification for job_areas
    classification_text = _extract_detail_field(html, "job-detail-classifications")

    job_areas: list[dict[str, str]] = []
    if classification_text:
        # Classification string like "Help Desk & IT Support (Information & Communication Technology)"
        # Split on parentheses to get sub-classification
        parts = classification_text.split("(")
        for part in parts:
            part = part.strip(") ").strip()
            if part:
                job_areas.append({"name": part})

    # Build apply URL
    apply_url = job_url.rstrip("/") + "/apply" if job_url else ""

    return JobDetail(
        description_html=description_html,
        company_description_html="",   # not available on JobsDB
        apply_url=apply_url,
        job_areas=job_areas,
        skills=[],                      # not available on JobsDB
    )


# --------------------------------------------------------------------------- #
# Page fetchers
# --------------------------------------------------------------------------- #

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class PlaywrightFetcher:
    """Fetch rendered page HTML via a headless Chromium browser.

    JobsDB is a client-rendered SPA behind Cloudflare, so a plain HTTP client
    is blocked (403) or gets an empty shell. Driving a real browser lets the
    page execute its JS, and ``networkidle`` waits for it to settle before the
    DOM is read. The browser + context are created once and reused for every
    fetch in the run (listing pages + job detail pages).
    """

    def __init__(
        self, *, headless: bool = True, timeout_ms: int = 30000,
        selector_timeout_ms: int = 15000, retries: int = 3,
    ) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright is not installed. "
                "Run: pip install playwright && playwright install chromium"
            ) from exc
        self._timeout_ms = timeout_ms
        self._selector_timeout_ms = selector_timeout_ms
        self._retries = retries
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._context = self._browser.new_context(user_agent=_USER_AGENT)

    def __enter__(self) -> "PlaywrightFetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._context.close()
            self._browser.close()
        finally:
            self._pw.stop()

    def fetch(self, url: str, *, wait_selector: str | None = None) -> str:
        """Return the rendered page HTML, or '' on failure.

        Uses ``domcontentloaded`` (not ``networkidle`` — JobsDB keeps long-lived
        connections, so networkidle never settles). If ``wait_selector`` is given,
        wait best-effort for it to appear so the SPA has rendered the content we
        need; if it never shows, return whatever DOM rendered rather than failing.
        """
        for attempt in range(1, self._retries + 1):
            page = self._context.new_page()
            try:
                print(
                    f"  [playwright] Fetching (try {attempt}/{self._retries}): {url}",
                    file=sys.stderr,
                )
                resp = page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
                if resp is None or not resp.ok:
                    raise RuntimeError(
                        f"HTTP {resp.status if resp else 'no response'}"
                    )
                if wait_selector:
                    try:
                        page.wait_for_selector(wait_selector, timeout=self._selector_timeout_ms)
                    except Exception:
                        print(
                            f"  [playwright] selector not seen, taking current DOM: {wait_selector}",
                            file=sys.stderr,
                        )
                return page.content()
            except Exception as e:
                print(f"  [playwright] Error: {e}", file=sys.stderr)
                if attempt < self._retries:
                    time.sleep(2 * attempt)
            finally:
                page.close()
        return ""


# --------------------------------------------------------------------------- #
# Core scraping logic
# --------------------------------------------------------------------------- #

def build_url(category: str, page: int) -> str:
    """Construct the JobsDB search URL for a category + page number."""
    return f"{BASE_URL}/jobs-in-{category}?page={page}"


def _empty_detail(job_url: str) -> dict[str, Any]:
    """Return empty detail fields for jobs where detail fetch failed."""
    return {
        "description_html": "",
        "company_description_html": "",
        "apply_url": job_url,
        "job_areas": [],
        "skills": [],
    }


def _fetch_detail(fetcher, job_id: str, job_url: str) -> dict[str, Any] | None:
    """Fetch and parse a job detail page. Returns the detail dict, or None on failure."""
    try:
        detail_html = fetcher(job_url, wait_selector='[data-automation="jobAdDetails"]')
        if detail_html:
            detail = parse_detail_page(detail_html, job_url)
            return {
                "description_html": detail.description_html,
                "company_description_html": detail.company_description_html,
                "apply_url": detail.apply_url,
                "job_areas": detail.job_areas,
                "skills": detail.skills,
            }
        print(f"  ⚠ No HTML for detail page: {job_url}", file=sys.stderr)
    except Exception as exc:
        print(f"  ! Detail fetch failed for {job_id}: {exc}", file=sys.stderr)
    return None


def scrape(
    *,
    category: str = DEFAULT_CATEGORY,
    start_page: int = 1,
    end_page: int = 1,
    delay: float = REQUEST_DELAY,
    detail_delay: float = DETAIL_DELAY,
    max_jobs: int = 0,
) -> list[dict[str, Any]]:
    """
    Scrape job listings from JobsDB across one or more pages.
    Returns a list of dicts with the **same schema as scraper_ctgoodjobs**.
    Only NEW jobs (not in fetched_job_ids.txt) are included in the output.
    """
    records: list[dict[str, Any]] = []

    # Load previously-fetched IDs — jobs in this list are skipped entirely
    fetched_ids: set[str] = load_fetched_ids()
    new_fetched_ids: set[str] = set()
    print(f"  [ids] {len(fetched_ids)} previously-fetched IDs loaded", file=sys.stderr)

    detail_fetched = 0
    detail_skipped = 0
    detail_failed = 0
    jobs_seen = 0
    quota_hit = False

    with PlaywrightFetcher() as pf:
        fetcher = pf.fetch

        for page in range(start_page, end_page + 1):
            url = build_url(category, page)
            print(f"\n  Page {page}/{end_page}: {url}", file=sys.stderr)

            html = fetcher(url, wait_selector='[data-automation="normalJob"]')
            if not html:
                print(f"  ⚠ No HTML returned for page {page}. Skipping.", file=sys.stderr)
                continue

            raw_jobs = parse_page(html)

            for raw in raw_jobs:
                summary = raw_to_job_summary(raw)
                jobs_seen += 1

                # Skip previously-fetched jobs entirely
                if summary.job_id and summary.job_id in fetched_ids:
                    detail_skipped += 1
                    continue

                if not summary.job_id:
                    # No job_id — can't track, include with empty detail
                    rec = asdict(summary)
                    rec.update(_empty_detail(summary.job_url))
                    records.append(rec)
                    continue

                # Fetch detail for new job
                detail_dict = _fetch_detail(fetcher, summary.job_id, summary.job_url)
                rec = asdict(summary)
                if detail_dict:
                    detail_fetched += 1
                    rec.update(detail_dict)
                    new_fetched_ids.add(summary.job_id)
                else:
                    detail_failed += 1
                    rec.update(_empty_detail(summary.job_url))
                records.append(rec)

                if detail_delay:
                    time.sleep(detail_delay)

                # Stop once the max-jobs quota is reached
                if max_jobs > 0 and detail_fetched >= max_jobs:
                    print(f"  [quota] Reached max-jobs limit ({max_jobs}). Stopping.", file=sys.stderr)
                    quota_hit = True
                    break

            print(f"  ✓ Found {len(raw_jobs)} jobs on page {page}", file=sys.stderr)

            if quota_hit:
                break

            if page < end_page:
                print(f"  ⏳ Waiting {delay}s…", file=sys.stderr)
                time.sleep(delay)

    # Save updated fetched IDs
    if new_fetched_ids:
        all_ids = fetched_ids | new_fetched_ids
        save_fetched_ids(all_ids)

    print(
        f"  [ids] {jobs_seen} jobs seen, {detail_skipped} skipped (already fetched), "
        f"{detail_fetched} detail fetched, {detail_failed} failed",
        file=sys.stderr,
    )
    print(f"\n  Total new jobs collected: {len(records)}", file=sys.stderr)
    return records


# --------------------------------------------------------------------------- #
# Output helpers  (same CSV_FIELDS and format as scraper_ctgoodjobs.py)
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
# CLI
# --------------------------------------------------------------------------- #

def parse_page_range(page_str: str) -> tuple[int, int]:
    """Parse '3' → (3,3) or '1-5' → (1,5)."""
    if "-" in page_str:
        parts = page_str.split("-", 1)
        return int(parts[0]), int(parts[1])
    p = int(page_str)
    return p, p


def main() -> int:
    load_dotenv()

    p = argparse.ArgumentParser(
        description="Scrape job ads from hk.jobsdb.com (output aligned with scraper_ctgoodjobs.py)",
    )
    p.add_argument(
        "--pages", default="1",
        help="Page(s) to scrape: '3' for page 3, '1-5' for pages 1-5 (default: 1)",
    )
    p.add_argument(
        "--category", default=DEFAULT_CATEGORY,
        help=f"Job category slug (default: {DEFAULT_CATEGORY})",
    )
    p.add_argument(
        "--output", default=DEFAULT_OUTPUT,
        help=f"Output file prefix (default: {DEFAULT_OUTPUT})",
    )
    p.add_argument(
        "--delay", type=float, default=REQUEST_DELAY,
        help=f"Seconds between page fetches (default: {REQUEST_DELAY})",
    )
    p.add_argument(
        "--detail-delay", type=float, default=DETAIL_DELAY,
        help=f"Seconds between detail page fetches (default: {DETAIL_DELAY})",
    )
    p.add_argument(
        "--format", choices=("csv", "json", "both"), default="json",
        help="Output format (default: both).",
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
        help=f"R2 folder prefix (default: {R2_PREFIX}). Use 'testing/jobsdb' for test runs.",
    )
    args = p.parse_args()

    start_page, end_page = parse_page_range(args.pages)

    # Sync fetched IDs from R2 before scraping
    if args.upload_r2:
        sync_fetched_ids_from_r2(r2_prefix=args.r2_prefix)

    print(file=sys.stderr)
    print("╔══════════════════════════════════════════════════╗", file=sys.stderr)
    print("║        JobsDB Hong Kong Job Scraper             ║", file=sys.stderr)
    print("╚══════════════════════════════════════════════════╝", file=sys.stderr)
    print(f"  Category   : {args.category}", file=sys.stderr)
    print(f"  Pages      : {start_page}–{end_page}", file=sys.stderr)
    print(f"  Fetcher    : playwright (headless chromium)", file=sys.stderr)
    if args.max_jobs:
        print(f"  Max jobs   : {args.max_jobs}", file=sys.stderr)
    print(f"  Output     : {args.output}.json / .csv", file=sys.stderr)
    print(f"  Upload R2  : {args.upload_r2}", file=sys.stderr)

    records = scrape(
        category=args.category,
        start_page=start_page,
        end_page=end_page,
        delay=args.delay,
        detail_delay=args.detail_delay,
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
