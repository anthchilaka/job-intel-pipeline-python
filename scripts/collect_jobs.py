"""
collect_jobs.py — Layer 1: Dual-source LinkedIn job collection
LinkedIn Job Intel — Anthony Chilaka

Sources:
  A. LinkedIn jobs-guest API (formal job listings, no login required)
  B. Google search for LinkedIn feed posts (informal "we're hiring" posts)

Usage:
  python collect_jobs.py --config ../config/anthony.json
  python collect_jobs.py --config ../config/mentees/user2.json

Output:
  Writes raw_jobs_YYYY-MM-DD.json to a temp folder for Claude to process.
  Also writes a human-readable raw_jobs_YYYY-MM-DD.md summary.
"""

import json
import os
import sys
import time
import argparse
import datetime
import requests
from urllib.parse import urlencode, quote_plus
from bs4 import BeautifulSoup


# ── Constants ─────────────────────────────────────────────────────────────────

LINKEDIN_JOBS_BASE = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)
LINKEDIN_JOB_DETAIL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
)
BRAVE_SEARCH_BASE = "https://api.search.brave.com/res/v1/web/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Polite delay between requests (seconds)
REQUEST_DELAY = 2

# Sender config path (relative to this script)
SENDER_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "sender.json")


# ── Config loader ────────────────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_sender_config() -> dict:
    path = os.path.normpath(SENDER_CONFIG_PATH)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Source A: LinkedIn jobs-guest API ────────────────────────────────────────

def fetch_linkedin_jobs(search_term: str, hours: int = 24, location: str = None, remote_only: bool = True) -> list[dict]:
    """
    Query LinkedIn jobs-guest API for a single search term.

    location_targets (e.g. South Africa, Nigeria) pass location= and
    remote_only=False so hybrid/onsite postings in that country aren't
    dropped by the f_WT=2 remote filter — Anthony can work those on-site.
    Returns a list of raw job dicts.
    """
    # f_WT=2  → remote only (omitted when remote_only=False)
    # f_TPR=r{seconds} → posted in last N hours
    seconds = hours * 3600
    params = {
        "keywords": search_term,
        "f_TPR": f"r{seconds}",
        "start": "0",
    }
    if remote_only:
        params["f_WT"] = "2"
    if location:
        params["location"] = location

    jobs = []
    url = f"{LINKEDIN_JOBS_BASE}?{urlencode(params)}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        job_cards = soup.find_all("li")

        for card in job_cards:
            job_id_tag = card.find("div", {"data-entity-urn": True})
            title_tag = card.find("h3")
            company_tag = card.find("h4")
            location_tag = card.find("span", class_=lambda c: c and "job-search-card__location" in c)
            date_tag = card.find("time")
            link_tag = card.find("a", href=True)

            if not title_tag:
                continue

            job_id = ""
            if job_id_tag:
                urn = job_id_tag.get("data-entity-urn", "")
                job_id = urn.split(":")[-1] if urn else ""

            jobs.append({
                "source": "linkedin_jobs_api",
                "job_id": job_id,
                "title": title_tag.get_text(strip=True) if title_tag else "",
                "company": company_tag.get_text(strip=True) if company_tag else "",
                "location": location_tag.get_text(strip=True) if location_tag else "",
                "date_posted": date_tag.get("datetime", "") if date_tag else "",
                "url": link_tag["href"].split("?")[0] if link_tag else "",
                "description": "",  # fetched separately below
                "search_term": search_term,
                # set by caller for location_targets passes (e.g. "South Africa");
                # None for the standard global-remote pass. Layer 2 uses this to
                # skip the remote-required check for on-site/hybrid African roles.
                "location_target": location,
            })

        time.sleep(REQUEST_DELAY)

    except Exception as e:
        print(f"  [WARNING] LinkedIn jobs-guest API error for '{search_term}': {e}")

    return jobs


def fetch_job_description(job_id: str) -> str:
    """
    Fetch full job description for a LinkedIn job posting by ID.
    """
    if not job_id:
        return ""
    url = LINKEDIN_JOB_DETAIL.format(job_id=job_id)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        desc_tag = soup.find("div", class_=lambda c: c and "description" in c.lower())
        if desc_tag:
            return desc_tag.get_text(separator="\n", strip=True)
    except Exception as e:
        print(f"  [WARNING] Could not fetch description for job {job_id}: {e}")
    return ""


# ── Source B: Brave Search API ─────────────────────────────────────────────

def fetch_linkedin_feed_posts(search_term: str, hours: int = 24) -> list[dict]:
    """
    Search for LinkedIn feed posts using the Brave Search API.
    Replaces Google CSE (closed to new customers as of early 2026).

    Runs 3 query variants per search term (different hiring phrases).
    Uses freshness=pd (last 24 hours) to match the collection window.
    Deduplicates by URL. Returns a list of raw post dicts.

    Credentials read from config/sender.json:
      brave_search_api_key — Brave Search API key (X-Subscription-Token)
    """
    try:
        sender = load_sender_config()
        api_key = sender["brave_search_api_key"]
    except (FileNotFoundError, KeyError) as e:
        print(f"  [ERROR] Could not load Brave Search API key from sender.json: {e}")
        return []

    today = datetime.date.today().strftime("%Y-%m-%d")

    # Three query variants — each targets different informal hiring phrasing
    queries = [
        f'site:linkedin.com/posts "we\'re hiring" "remote" "{search_term}"',
        f'site:linkedin.com/posts "open role" OR "open position" "{search_term}" remote',
        f'site:linkedin.com/posts "join our team" "{search_term}" remote',
    ]

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }

    posts = []
    seen_urls: set[str] = set()

    for query in queries:
        params = {
            "q": query,
            "count": 20,
            # freshness=pd disabled — Brave's site: operator + freshness conflict (operators are experimental)
            # Layer 2 handles stale/irrelevant posts downstream
            "safesearch": "off",
        }

        try:
            resp = requests.get(BRAVE_SEARCH_BASE, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("web", {}).get("results", []):
                href = item.get("url", "")
                if not href or href in seen_urls:
                    continue
                if "linkedin.com" not in href:
                    continue
                seen_urls.add(href)

                posts.append({
                    "source": "linkedin_feed_post",
                    "job_id": "",
                    "title": item.get("title", ""),
                    "company": "",
                    "location": "Remote (feed post — verify)",
                    "date_posted": today,
                    "url": href,
                    "description": item.get("description", ""),
                    "search_term": search_term,
                })

            time.sleep(REQUEST_DELAY)

        except Exception as e:
            print(
                f"  [WARNING] Brave Search error for '{search_term}' "
                f"(query: {query[:60]}...): {e}"
            )

    return posts


# ── Deduplication ────────────────────────────────────────────────────────

def deduplicate(jobs: list[dict]) -> list[dict]:
    """
    Deduplicate by URL. First occurrence of each URL is kept.
    """
    seen_urls = set()
    unique = []
    for job in jobs:
        url = job.get("url", "").strip().rstrip("/")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(job)
    return unique


# ── Output writers ────────────────────────────────────────────────────

def write_json_output(jobs: list[dict], output_dir: str, date_str: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"raw_jobs_{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    return path


def write_md_summary(jobs: list[dict], output_dir: str, date_str: str) -> str:
    """
    Write a human-readable markdown summary of raw collected jobs.
    This is what Claude reads to run Layers 2–6.
    """
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"raw_jobs_{date_str}.md")

    api_jobs = [j for j in jobs if j["source"] == "linkedin_jobs_api"]
    feed_posts = [j for j in jobs if j["source"] == "linkedin_feed_post"]

    lines = [
        f"# Raw LinkedIn Job Batch — {date_str}",
        f"",
        f"**Total collected:** {len(jobs)} ({len(api_jobs)} from LinkedIn Jobs API, {len(feed_posts)} from LinkedIn feed)",
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


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LinkedIn Job Intel — Layer 1 collector")
    parser.add_argument("--config", required=True, help="Path to user config JSON")
    args = parser.parse_args()

    config = load_config(args.config)
    search_terms = config.get("search_terms", [])
    hours = config.get("collection_window_hours", 24)
    output_path = config.get("output_path", ".")
    temp_dir = os.path.join(output_path, "_temp")
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    location_targets = config.get("location_targets", [])

    print(f"\nLinkedIn Job Intel — Layer 1 Collection")
    print(f"User: {config.get('name', 'Unknown')}")
    print(f"Date: {date_str}")
    print(f"Search terms: {search_terms}")
    print(f"Window: last {hours} hours")
    if location_targets:
        print(f"Location targets: {[lt['location'] for lt in location_targets]}")
    print(f"Output path: {output_path}\n")

    all_jobs = []

    for term in search_terms:
        print(f"[Source A] LinkedIn Jobs API — '{term}'")
        jobs = fetch_linkedin_jobs(term, hours)
        print(f"  Found {len(jobs)} listings")

        # Fetch descriptions for API jobs
        for job in jobs:
            if job["job_id"]:
                job["description"] = fetch_job_description(job["job_id"])
                time.sleep(REQUEST_DELAY)

        all_jobs.extend(jobs)

        print(f"[Source B] Brave Search feed search — '{term}'")
        posts = fetch_linkedin_feed_posts(term, hours)
        print(f"  Found {len(posts)} feed posts")
        all_jobs.extend(posts)

        # Standing African-market coverage — hybrid/onsite postings in these
        # countries are workable on-site, so remote_only=False and a wider
        # window (these markets post less frequently per day).
        for lt in location_targets:
            loc = lt["location"]
            loc_hours = lt.get("window_hours", hours)
            print(f"[Source A — {loc}] LinkedIn Jobs API — '{term}'")
            loc_jobs = fetch_linkedin_jobs(term, loc_hours, location=loc, remote_only=lt.get("remote_required", False))
            print(f"  Found {len(loc_jobs)} listings")
            for job in loc_jobs:
                if job["job_id"]:
                    job["description"] = fetch_job_description(job["job_id"])
                    time.sleep(REQUEST_DELAY)
            all_jobs.extend(loc_jobs)

    print(f"\nDeduplicating {len(all_jobs)} total results...")
    unique_jobs = deduplicate(all_jobs)
    print(f"Unique after deduplication: {len(unique_jobs)}")

    json_path = write_json_output(unique_jobs, temp_dir, date_str)
    md_path = write_md_summary(unique_jobs, temp_dir, date_str)

    print(f"\nOutput written:")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")
    print(f"\nLayer 1 complete. Hand the MD file to Claude to run Layers 2–6.")


if __name__ == "__main__":
    main()
