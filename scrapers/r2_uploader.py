#!/usr/bin/env python3
"""
r2_uploader.py — Upload files to Cloudflare R2 via S3-compatible API

Usage (standalone):
    python3 r2_uploader.py <local_path> <r2_key>

Environment variables (or .env file in project root):
    R2_ACCOUNT_ID        Cloudflare account ID
    R2_ACCESS_KEY_ID     R2 API token access key
    R2_SECRET_ACCESS_KEY R2 API token secret key
    R2_BUCKET_NAME       R2 bucket name
    R2_REGION            Region (default: auto)
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.config import Config


# --------------------------------------------------------------------------- #
# .env loader (minimal — no dependency on python-dotenv)
# --------------------------------------------------------------------------- #

def load_dotenv(path: str | Path | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (no override)."""
    if path is None:
        path = Path(__file__).resolve().parent / ".env"
    path = Path(path)
    if not path.exists():
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            # Strip surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key not in os.environ:  # don't overwrite existing
                os.environ[key] = value


# --------------------------------------------------------------------------- #
# R2 client
# --------------------------------------------------------------------------- #

def _env(name: str, *, required: bool = True) -> str:
    val = os.environ.get(name, "")
    if required and not val:
        raise EnvironmentError(
            f"Required environment variable {name} is not set. "
            f"Add it to your .env file (see .env.example)."
        )
    return val


@lru_cache(maxsize=1)
def get_r2_client():
    """Return a boto3 S3 client pointed at Cloudflare R2.

    Cached so a run that uploads several objects (JSON + fetched_job_ids sync)
    reuses one client instead of rebuilding boto3 each call.
    """
    account_id = _env("R2_ACCOUNT_ID")
    access_key = _env("R2_ACCESS_KEY_ID")
    secret_key = _env("R2_SECRET_ACCESS_KEY")
    region = os.environ.get("R2_REGION", "auto")

    endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )


def upload_to_r2(
    local_path: str,
    r2_key: str,
    *,
    bucket: str | None = None,
    content_type: str | None = None,
) -> str:
    """
    Upload a local file to R2.

    Args:
        local_path:  Path to the local file.
        r2_key:      Object key in the bucket (e.g. "ctgoodjobs/2025-01-15.json").
        bucket:      Bucket name (defaults to R2_BUCKET_NAME env var).
        content_type: MIME type (auto-detected if omitted).

    Returns:
        The R2 key that was written.
    """
    bucket = bucket or _env("R2_BUCKET_NAME")
    client = get_r2_client()

    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type
    elif r2_key.endswith(".json"):
        extra_args["ContentType"] = "application/json"
    elif r2_key.endswith(".csv"):
        extra_args["ContentType"] = "text/csv"
    elif r2_key.endswith(".txt"):
        extra_args["ContentType"] = "text/plain"

    print(f"  [R2] Uploading {local_path} → {bucket}/{r2_key}", file=sys.stderr)
    client.upload_file(local_path, bucket, r2_key, ExtraArgs=extra_args or None)
    print(f"  [R2] ✓ Uploaded", file=sys.stderr)
    return r2_key


def download_from_r2(
    r2_key: str,
    local_path: str,
    *,
    bucket: str | None = None,
) -> bool:
    """
    Download a file from R2. Returns True if successful, False if not found.
    """
    bucket = bucket or _env("R2_BUCKET_NAME")
    client = get_r2_client()
    try:
        print(f"  [R2] Downloading {bucket}/{r2_key} → {local_path}", file=sys.stderr)
        client.download_file(bucket, r2_key, local_path)
        print(f"  [R2] ✓ Downloaded", file=sys.stderr)
        return True
    except client.exceptions.NoSuchKey:
        print(f"  [R2] Key not found: {r2_key}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"  [R2] Download error: {exc}", file=sys.stderr)
        return False


# --------------------------------------------------------------------------- #
# Output-path helpers (shared by scrapers)
# --------------------------------------------------------------------------- #

def output_target(
    data_root: Path, source: str, stem: str, ext: str
) -> tuple[str, str]:
    """Local write path under <data_root>/<source>/ and the mirroring R2 key.

    The R2 key is the local path with the data root stripped — the R2 bucket
    plays the role of <data_root>. Built once so the two can never drift.
    """
    fname = f"{stem}.{ext}"
    return str(data_root / source / fname), f"{source}/{fname}"


# --------------------------------------------------------------------------- #
# Standalone CLI
# --------------------------------------------------------------------------- #

def main() -> int:
    load_dotenv()
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <local_path> <r2_key>", file=sys.stderr)
        return 1
    upload_to_r2(sys.argv[1], sys.argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main())
