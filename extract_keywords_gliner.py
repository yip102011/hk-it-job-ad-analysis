"""Extract keywords from a scraped job-ad JSON file using GLiNER.

Usage:
    # default output: <input_stem>_keywords.json next to the input
    python extract_keywords_gliner.py data/jobsdb/jobsdb_jobs_20260703.json

    # explicit output + looser confidence threshold
    python extract_keywords_gliner.py data/ctgoodjobs/ctgoodjobs_jobs_20260703.json \
        -o out.json --threshold 0.4

Input : a JSON array of jobs (jobsdb / ctgoodjobs scraper output). Keywords are
        extracted from each job's `description` field (HTML-stripped body the
        scraper writes); falls back to stripping description_html if absent.
Output: a JSON array of {job_id, job_title, description, keywords: {label: [terms]}},
        one entry per job. `description` is the text keywords were extracted
        from; terms are deduped case-insensitively.
"""

import argparse
import json
import os
import re
from html import unescape
from pathlib import Path

from gliner import GLiNER

LABELS = [
    "software",
    "technology",
    "programming language",
    "methodology",
    "concept",
    "location",
    "position",
]

MODEL_ID = "urchade/gliner_medium-v2.1"
MODEL_DIR = Path(__file__).parent / "models" / "gliner_medium-v2.1"

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(html: str) -> str:
    # ponytail: regex over an HTML lib — fine for job-ad markup; leaves plain whitespace.
    return unescape(_TAG_RE.sub(" ", html)).strip()


def job_text(job: dict) -> str:
    # Prefer the scraper's pre-stripped `description`; fall back to stripping
    # description_html for older data that predates the field.
    return job.get("description") or strip_html(job.get("description_html") or "")


def load_model() -> GLiNER:
    # Warm: load from the local dir with the hub disabled → no "Fetching" and no
    # auth ping for the encoder tokenizer (cached in the HF cache). Cold: download
    # the GLiNER weights into MODEL_DIR once (the encoder tokenizer caches too).
    if MODEL_DIR.is_dir() and any(MODEL_DIR.iterdir()):
        os.environ["HF_HUB_OFFLINE"] = "1"
        import huggingface_hub

        huggingface_hub.constants.HF_HUB_OFFLINE = True  # env var is read at import time
        return GLiNER.from_pretrained(str(MODEL_DIR))
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    from huggingface_hub import snapshot_download

    snapshot_download(repo_id=MODEL_ID, local_dir=str(MODEL_DIR))
    return GLiNER.from_pretrained(str(MODEL_DIR))


def predict_entities(model: GLiNER, text: str, threshold: float) -> list[dict]:
    """Run GLiNER over text, chunking long input at word boundaries.

    GLiNER-medium caps input near 384 tokens and silently truncates longer text,
    dropping tail-end skills. We split on word boundaries (lengths measured with
    the model's own tokenizer) so no entity is cut and the whole text is covered.
    """
    tokenizer = model.data_processor.transformer_tokenizer
    limit = getattr(model.config, "max_length", 384) - 64  # room for special + label tokens

    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for w in text.split():
        wl = len(tokenizer.encode(w, add_special_tokens=False))
        if cur and cur_len + wl > limit:
            chunks.append(" ".join(cur))
            cur, cur_len = [], 0
        cur.append(w)
        cur_len += wl
    if cur:
        chunks.append(" ".join(cur))

    ents: list[dict] = []
    for chunk in chunks:
        ents.extend(model.predict_entities(chunk, LABELS, threshold=threshold))
    return ents


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract keywords from a scraped job JSON file with GLiNER.")
    ap.add_argument("input", type=Path, help="Input job JSON file (list of jobs).")
    ap.add_argument("-o", "--output", type=Path, help="Output JSON path (default: <input>_keywords.json).")
    ap.add_argument("--threshold", type=float, default=0.5, help="Entity confidence threshold.")
    args = ap.parse_args()

    out_path = args.output or args.input.with_name(f"{args.input.stem}_keywords.json")
    jobs = json.loads(args.input.read_text(encoding="utf-8", errors="ignore"))

    model = load_model()

    results = []
    for job in jobs:
        text = job_text(job)
        keywords: dict[str, list[str]] = {}
        seen: set[str] = set()
        for ent in predict_entities(model, text, args.threshold):
            key = ent["text"].strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            keywords.setdefault(ent["label"], []).append(ent["text"].strip())
        results.append(
            {
                "job_id": job.get("job_id"),
                "job_title": job.get("job_title"),
                "description": text,
                "keywords": keywords,
            }
        )

    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(results)} jobs -> {out_path}")


if __name__ == "__main__":
    main()
