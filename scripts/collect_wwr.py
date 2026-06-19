"""
collect_wwr.py — Layer 1: We Work Remotely job collection
LinkedIn Job Intel — Anthony Chilaka

Source:   We Work Remotely (weworkremotely.com) — curated, remote-first job board.
          Higher editorial bar than LinkedIn — no third-party recruiters, no agency spam.
Method:   RSS feed via feedparser — no JS rendering, no browser required.
          WWR publishes a public feed per category. This script reads multiple category
          feeds and filters entries by the user's configured search terms.

FIRST-TIME SETUP (one-time, run in terminal):
  pip install feedparser

Usage:
  python collect_wwr.py --config ../config/anthony.json
  python collect_wwr.py --config ../config/mentees/user2.json

Output (written to config["output_path"]/_temp/):
  raw_wwr_YYYY-MM-DD.json   — machine-readable, full detail
  raw_wwr_YYYY-MM-DD.md     — human-readable, for Claude Layer 2

RSS feed format notes (if WWR changes their feed structure):
  - entry.title:    "CompanyName: Job Title" (WWR convention)
  - entry.link:     Direct job URL
  - entry.published_parsed or entry.updated_parsed: posting date (struct_time)
  - entry.summary:  HTML description

Category feed URLs (add or remove as needed in WWR_FEEDS below):
  - All jobs:       https://weworkremotely.com/remote-jobs.rss
  - Data Science:   https://weworkremotely.com/categories/remote-data-science-jobs.rss
  - Business/Exec:  https://weworkremotely.com/categories/remote-business-exec-and-management-jobs.rss
  - Marketing:      https://weworkremotely.com/categories/remote-marketing-jobs.rss
  - Finance/Legal:  https://weworkremotely.com/categories/remote-finance-and-legal-jobs.rss
"""

import json
import os
import re
import sys
import time
import argparse
import datetime
import calendar

try:
    import feedparser
except ImportError:
    print("[ERROR] feedparser not installed.")
    print("  Run: pip install feedparser")
    print("  PyPI: https://pypi.org/project/feedparser/")
    sys.exit(1)


# ── RSS Feed URLs ───────────────────────────────────────────────────────
# WWR publishes one general feed covering all categories.
# Category-specific feeds exist but use unpredictable slugs that break without warning.
# Using the general feed is more reliable — term+description filtering handles relevance.
#
# To verify the current general feed URL: visit weworkremotely.com and check the RSS
# link in the page header, or look for the RSS icon in the browser address bar.

WWR_FEEDS = [
    {
        "url": "https://weworkremotely.com/remote-jobs.rss",
        "category": "All Jobs",
    },
]

# Legacy: category-specific feed URLs (kept here for reference if WWR re-enables them)
# These returned 0 entries in testing (May 2026) — slugs appear to be inactive.
# If you want to try them, move entries back into WWR_FEEDS above.
#
# "https://weworkremotely.com/categories/remote-data-science-jobs.rss"       — Data Science
# "https://weworkremotely.com/categories/remote-programming-jobs.rss"        — Programming
# "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss" — Business
# "https://weworkremotely.com/categories/remote-marketing-jobs.rss"          — Marketing

# Fallback is no longer needed since we use the general feed directly,
# but kept for compatibility with the fetch loop below.
WWR_GENERAL_FEED = "https://weworkremotely.com/remote-jobs.rss"

# Seconds to wait between feed fetches (polite crawl rate)
FEED_REQUEST_DELAY = 2

# Minimum title length to skip empty/malformed entries
MIN_TITLE_LENGTH = 4


# ── Config loader ──────────────────────────────────────────────────────────

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Title parser ──────────────────────────────────────────────────────────────

def parse_wwr_title(raw_title: str) -> tuple[str, str]:
    """
    WWR RSS titles follow the convention: "Company: Job Title"
    Split on the first colon to extract company and job title.
    If no colon found, treat the entire string as the title with no company.

    Returns: (company, title)
    """
    if ":" in raw_title:
        parts = raw_title.split(":", 1)
        company = parts[0].strip()
        title = parts[1].strip()
        return company, title
    return "", raw_title.strip()


# ── Date helpers ─────────────────────────────────────────────────────────────

def entry_datetime(entry) -> datetime.datetime | None:
    """
    Extract a datetime from a feedparser entry.
    Tries published_parsed first, falls back to updated_parsed.
    Returns a timezone-aware UTC datetime, or None if not available.
    """
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t is not None:
            try:
                return datetime.datetime.fromtimestamp(
                    calendar.timegm(t), tz=datetime.timezone.utc
                )
            except Exception:
                pass
    return None


def is_within_window(entry, hours: int) -> bool:
    """Return True if the entry was posted within the last N hours."""
    if hours <= 0:
        return True  # No window — include all
    dt = entry_datetime(entry)
    if dt is None:
        return True  # Unknown date — include rather than miss
    cutoff = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(hours=hours)
    return dt >= cutoff


# ── Search term filter ─────────────────────────────────────────────────────

def matches_search_terms(text: str, search_terms: list[str]) -> str | None:
    """
    Return the first matching search term if the text contains it (case-insensitive).
    Text is the combined job title + description — catches terms that appear in the
    job description but not the title (common on WWR where titles are short).
    Returns None if no match.
    """
    text_lower = text.lower()
    for term in search_terms:
        if term.lower() in text_lower:
            return term
    return None


# ── Strip HTML ─────────────────────────────────────────────────────────────────

def strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace. Used for summary text."""
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


# ── Feed reader ─────────────────────────────────────────────────────────────

def fetch_feed(feed_url: str, category: str, search_terms: list[str],
               window_hours: int, date_str: str) -> list[dict]:
    """
    Fetch a single WWR RSS feed, filter by search terms and date window.

    Args:
        feed_url:      RSS URL to fetch
        category:      Human-readable category label for logging
        search_terms:  List of search terms from user config
        window_hours:  collection_window_hours from config (0 = no filter)
        date_str:      YYYY-MM-DD string for date_posted field

    Returns:
        List of job dicts matching the search terms and date window
    """
    print(f"  -> [{category}] {feed_url}")
    jobs = []

    try:
        feed = feedparser.parse(feed_url)
    except Exception as e:
        print(f"  [ERROR] Failed to fetch feed: {e}")
        return jobs

    if feed.bozo:
        # bozo flag means feedparser encountered a non-critical parse error
        # Usually still usable — log a warning but continue
        print(f"  [WARNING] Feed parse warning (bozo): {getattr(feed, 'bozo_exception', 'unknown')}")

    total_entries = len(feed.entries)
    print(f"  Total entries in feed: {total_entries}")

    date_filtered = 0
    term_filtered = 0

    for entry in feed.entries:
        # Date window filter
        if not is_within_window(entry, window_hours):
            date_filtered += 1
            continue

        raw_title = getattr(entry, "title", "").strip()
        if not raw_title or len(raw_title) < MIN_TITLE_LENGTH:
            continue

        company, title = parse_wwr_title(raw_title)

        # Extract summary early — used in term matching AND output
        summary_html = getattr(entry, "summary", "")
        summary = strip_html(summary_html)
        if len(summary) > 400:
            summary = summary[:400].rsplit(" ", 1)[0] + "…"

        # Search term filter — match against title OR description combined
        # WWR titles are short ("Data Analyst") — the niche terms often appear
        # in the description text, not the title itself.
        matched_term = matches_search_terms(f"{title} {summary}", search_terms)
        if matched_term is None:
            term_filtered += 1
            continue

        url = getattr(entry, "link", "").strip()
        if not url:
            continue

        # Date posted
        dt = entry_datetime(entry)
        posted = dt.strftime("%Y-%m-%d") if dt else date_str

        jobs.append({
            "source": "weworkremotely",
            "job_id": url.rstrip("/").split("/")[-1],
            "title": title,
            "company": company,
            "location": "Remote",
            "date_posted": posted,
            "url": url,
            "description": summary,
            "search_term": matched_term,
            "wwr_category": category,
        })

    print(f"  After date filter: {total_entries - date_filtered} entries")
    print(f"  After term filter: {len(jobs)} matched ({term_filtered} excluded by term)")

    return jobs


# ── Deduplication ─────────────────────────────────────────────────────────

def deduplicate(jobs: list) -> list:
    """Deduplicate by URL. First occurrence wins."""
    seen = set()
    unique = []
    for job in jobs:
        key = job.get("url", "").strip().rstrip("/")
        if key and key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


# ── Output writers ────────────────────────────────────────────────────

def write_json(jobs: list, output_dir: str, date_str: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"raw_wwr_{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    return path


def write_md(jobs: list, output_dir: str, date_str: str) -> str:
    """
    Write human-readable markdown summary.
    Format matches raw_jobs_YYYY-MM-DD.md so Layers 2–7 work without modification.
    """
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"raw_wwr_{date_str}.md")

    lines = [
        f"# Raw We Work Remotely Job Batch — {date_str}",
        f"",
        f"**Source:** We Work Remotely (weworkremotely.com) — curated remote-first job board, editorial curation",
        f"**Total collected:** {len(jobs)}",
        f"**Status:** Unfiltered — awaiting Layer 2 global talent filter",
        f"",
        f"---",
        f"",
    ]

    for i, job in enumerate(jobs, 1):
        lines += [
            f"## Job {i}: {job['title'] or '(no title)'}",
            f"**Source:** {job['source']} ({job.get('wwr_category', 'Unknown category')})",
            f"**Company:** {job['company'] or '(not extracted)'}",
            f"**Location:** {job['location']}",
            f"**Date Posted:** {job['date_posted']}",
            f"**URL:** {job['url']}",
            f"**Search Term Match:** {job['search_term']}",
            f"",
            f"**Description:**",
            f"{job['description'] or '(see listing)'}",
            f"",
            f"---",
            f"",
        ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return path


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="LinkedIn Job Intel — We Work Remotely Layer 1 collector"
    )
    parser.add_argument("--config", required=True, help="Path to user config JSON")
    args = parser.parse_args()

    config = load_config(args.config)
    search_terms = config.get("search_terms", [])
    output_path = config.get("output_path", ".")
    window_hours = config.get("collection_window_hours", 24)
    temp_dir = os.path.join(output_path, "_temp")
    date_str = datetime.date.today().strftime("%Y-%m-%d")

    print(f"\nLinkedIn Job Intel — We Work Remotely Layer 1 Collection")
    print(f"User:            {config.get('name', 'Unknown')}")
    print(f"Date:            {date_str}")
    print(f"Search terms:    {search_terms}")
    print(f"Window:          last {window_hours}h")
    print(f"Output:          {temp_dir}")
    print()

    all_jobs = []

    for feed_info in WWR_FEEDS:
        print(f"[WWR] Fetching: {feed_info['category']}")
        jobs = fetch_feed(
            feed_url=feed_info["url"],
            category=feed_info["category"],
            search_terms=search_terms,
            window_hours=window_hours,
            date_str=date_str,
        )
        all_jobs.extend(jobs)
        print(f"  Running total: {len(all_jobs)}\n")
        time.sleep(FEED_REQUEST_DELAY)

    print(f"Deduplicating {len(all_jobs)} collected jobs...")
    unique = deduplicate(all_jobs)
    print(f"Unique after deduplication: {len(unique)}")

    json_path = write_json(unique, temp_dir, date_str)
    md_path = write_md(unique, temp_dir, date_str)

    print(f"\nOutput written:")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")
    print(f"\nWe Work Remotely Layer 1 complete.")

    if len(unique) == 0:
        print("\n[NOTE] Zero jobs collected.")
        print("  Possible causes:")
        print("  1. No new WWR listings in the last 24h match your search terms.")
        print("  2. Search terms too specific — check if the terms appear in job TITLES on weworkremotely.com.")
        print("  3. WWR changed their RSS feed URL or structure — check the URLs in WWR_FEEDS at the top of this script.")

    print(f"\nHand the MD file to Claude to run Layer 2 filtering.")


if __name__ == "__main__":
    main()
