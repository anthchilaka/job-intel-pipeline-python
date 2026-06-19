"""
collect_jobspy.py — Layer 1: JobSpy LinkedIn collector (Source D)
LinkedIn Job Intel — Anthony Chilaka

Source D catches LinkedIn job listings (formal and informal) more reliably
than the raw jobs-guest API, using built-in anti-detection and rate limiting.
Runs alongside collect_jobs.py. Output lands in the same _temp folder.

Usage:
  python collect_jobspy.py --config ../config/anthony.json
  python collect_jobspy.py --config ../config/mentees/user2.json

Output:
  raw_jobspy_YYYY-MM-DD.json
  raw_jobspy_YYYY-MM-DD.md
  Both written to the _temp folder defined in the user config.

Dependencies:
  pip install jobspy
"""

import argparse
import json
from datetime import date
from pathlib import Path

try:
    from jobspy import scrape_jobs
except ImportError:
    raise SystemExit(
        "[ERROR] jobspy not installed. Run:  pip install jobspy\n"
        "Then retry this script."
    )


# ── Config loader ────────────────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Collector ────────────────────────────────────────────────────────────────

def collect(config: dict) -> list[dict]:
    """
    Run JobSpy for each search term in the config.
    Returns a deduplicated list of job dicts.
    """
    search_terms = config.get("search_terms", [])
    all_jobs: list[dict] = []
    seen_urls: set[str] = set()
    today = date.today().isoformat()

    for term in search_terms:
        print(f"[JobSpy] Searching: {term}")
        try:
            results = scrape_jobs(
                site_name=["linkedin"],
                search_term=term,
                location="Worldwide",
                results_wanted=25,
                hours_old=24,
                linkedin_fetch_description=True,
            )

            for _, row in results.iterrows():
                url = str(row.get("job_url", "")).strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                all_jobs.append({
                    "source": "jobspy_linkedin",
                    "job_id": "",
                    "title": str(row.get("title", "")),
                    "company": str(row.get("company", "")),
                    "location": str(row.get("location", "")),
                    "date_posted": str(row.get("date_posted", today)),
                    "url": url,
                    "description": str(row.get("description", "")),
                    "search_term": term,
                })

        except Exception as e:
            print(f"[JobSpy] Error on '{term}': {e}")

    return all_jobs


# ── Output writers ──────────────────────────────────────────────────

def write_json(jobs: list[dict], output_dir: Path, today: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"raw_jobspy_{today}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    return path


def write_md(jobs: list[dict], output_dir: Path, today: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"raw_jobspy_{today}.md"

    lines = [
        f"# Raw JobSpy LinkedIn Batch — {today}",
        f"",
        f"**Total collected:** {len(jobs)} (deduplicated across search terms)",
        f"**Status:** Unfiltered — awaiting Layer 2 global talent filter",
        f"",
        f"---",
        f"",
    ]

    for i, job in enumerate(jobs, 1):
        lines += [
            f"## Job {i}: {job['title'] or '(no title)'}",
            f"**Source:** {job['source']}",
            f"**Company:** {job['company'] or '(not extracted)'}",
            f"**Location:** {job['location']}",
            f"**Date Posted:** {job['date_posted']}",
            f"**URL:** {job['url']}",
            f"**Search Term Match:** {job['search_term']}",
            f"",
            f"**Description:**",
            f"{job['description'] or '(no description extracted — see URL)'}",
            f"",
            f"---",
            f"",
        ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return path


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LinkedIn Job Intel — Layer 1 JobSpy collector")
    parser.add_argument("--config", required=True, help="Path to user config JSON")
    args = parser.parse_args()

    config = load_config(args.config)
    output_path = Path(config.get("output_path", "."))
    temp_dir = output_path / "_temp"
    today = date.today().isoformat()

    print(f"\nLinkedIn Job Intel — Layer 1 JobSpy Collection (Source D)")
    print(f"User: {config.get('name', 'Unknown')}")
    print(f"Date: {today}")
    print(f"Search terms: {config.get('search_terms', [])}")
    print(f"Output path: {output_path}\n")

    jobs = collect(config)

    print(f"\nTotal collected: {len(jobs)} (deduplicated)")

    json_path = write_json(jobs, temp_dir, today)
    md_path = write_md(jobs, temp_dir, today)

    print(f"\nOutput written:")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")
    print(f"\nSource D complete. Claude will merge this with raw_jobs_{today}.md in Layer 2.")


if __name__ == "__main__":
    main()
