"""
collect_wellfound.py — Layer 1: Wellfound job collection
LinkedIn Job Intel — Anthony Chilaka

Source:   Wellfound (wellfound.com) — startup-focused, company-verified job board
          (formerly AngelList Talent)
Method:   Playwright (sync API)
          Wellfound search pages are JS-rendered. requests + BeautifulSoup will NOT work.

FIRST-TIME SETUP (one-time, run in terminal):
  pip install playwright beautifulsoup4
  playwright install chromium

Usage:
  python collect_wellfound.py --config ../config/anthony.json
  python collect_wellfound.py --config ../config/mentees/user2.json
  python collect_wellfound.py --config ../config/anthony.json --debug

Output (written to config["output_path"]/_temp/):
  raw_wellfound_YYYY-MM-DD.json   — machine-readable, full detail
  raw_wellfound_YYYY-MM-DD.md     — human-readable, for Claude Layer 2

If selectors break after a Wellfound redesign:
  1. Run with --debug to save the rendered page HTML to _temp/
  2. Open the HTML file, search for job titles or company names to find new patterns
  3. Update LINK_HREF_PATTERNS and COMPANY_LINK_PATTERN at the top of this file
"""

import json
import os
import re
import sys
import time
import argparse
import datetime
from urllib.parse import urlencode

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("[ERROR] playwright not installed.")
    print("  Run: pip install playwright && playwright install chromium")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("[ERROR] beautifulsoup4 not installed.")
    print("  Run: pip install beautifulsoup4")
    sys.exit(1)

try:
    from playwright_stealth import Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False
    print("[WARNING] playwright-stealth not installed — Wellfound may block the request.")
    print("  Run: pip install playwright-stealth")


# ── Selectors — update here if Wellfound redesigns ────────────────────────────

WELLFOUND_BASE = "https://wellfound.com"
WELLFOUND_SEARCH = f"{WELLFOUND_BASE}/jobs"

# href must contain one of these patterns to be treated as a job link
LINK_HREF_PATTERNS = ["/jobs/", "/role/"]

# href must contain this to be treated as a company link (used to extract company name)
COMPANY_LINK_PATTERN = "/company/"

# Salary patterns: "$80k – $120k" or "$80,000 – $120,000"
SALARY_PATTERN = re.compile(r"\$[\d,]+[kK]?\s*[–\-]\s*\$[\d,]+[kK]?")

# Equity patterns: "0.10% – 0.50%"
EQUITY_PATTERN = re.compile(r"\d+\.?\d*%\s*[–\-]\s*\d+\.?\d*%")


# ── Constants ─────────────────────────────────────────────────────────

REQUEST_DELAY = 3        # Seconds between search term requests (polite crawl rate)
SCROLL_COUNT = 4         # How many times to scroll down to trigger lazy-load
SCROLL_PAUSE_MS = 1500   # ms to wait after each scroll
REACT_SETTLE_MS = 2000   # ms extra wait for React to finish rendering after scroll
PAGE_LOAD_TIMEOUT = 30000  # ms
MAX_JOBS_PER_SEARCH = 40  # Cap per search term to avoid excessive scraping

# Minimum title character length — filters out icon links and empty anchors
MIN_TITLE_LENGTH = 4


# ── Config loader ──────────────────────────────────────────────────────────

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── URL builder ───────────────────────────────────────────────────────────────

def build_search_url(search_term: str) -> str:
    """Build a Wellfound remote job search URL for the given search term."""
    return f"{WELLFOUND_SEARCH}?{urlencode({'query': search_term, 'remote': 'true'})}"


# ── DOM helpers ───────────────────────────────────────────────────────────────

def find_company_name(a_tag) -> str:
    """
    Walk up from a job link to find the nearest company link in the same card.
    Wellfound groups roles under company cards — company name is in an <a href="/company/..."> tag.
    """
    node = a_tag.parent
    for _ in range(10):
        if node is None:
            break
        company_link = node.find("a", href=lambda h: h and COMPANY_LINK_PATTERN in h)
        if company_link:
            name = company_link.get_text(strip=True)
            if name:
                return name
        node = node.parent
    return ""


def find_location(a_tag) -> str:
    """
    Look for a location signal near the job link.
    Wellfound remote roles typically carry a "Remote" tag. Defaults to "Remote".
    """
    node = a_tag.parent
    for _ in range(8):
        if node is None:
            break
        text = node.get_text(separator=" ", strip=True).lower()
        if "remote" in text:
            return "Remote"
        node = node.parent
    return "Remote"


def find_compensation(a_tag) -> str:
    """
    Look for salary or equity range in the job card near the link.
    Returns a formatted string like "Salary: $80k – $120k | Equity: 0.10% – 0.50%"
    or an empty string if nothing is found.
    """
    node = a_tag.parent
    for _ in range(8):
        if node is None:
            break
        text = node.get_text(separator=" ", strip=True)
        salary_match = SALARY_PATTERN.search(text)
        equity_match = EQUITY_PATTERN.search(text)
        if salary_match or equity_match:
            parts = []
            if salary_match:
                parts.append(f"Salary: {salary_match.group()}")
            if equity_match:
                parts.append(f"Equity: {equity_match.group()}")
            return " | ".join(parts)
        node = node.parent
    return ""


# ── Scraper ─────────────────────────────────────────────────────────────────

def scrape_search_page(page, search_term: str, date_str: str, debug_dir: str = None) -> list:
    """
    Navigate to a Wellfound search results page and extract job listings.

    Strategy:
      1. Load page with Playwright (handles JS rendering)
      2. Scroll to trigger lazy-loading of additional results
      3. Capture rendered HTML and parse with BeautifulSoup
      4. Find job links by href pattern (/jobs/ or /role/)
      5. For each link, walk the DOM upward to extract company name and comp info

    Args:
        page:        Playwright page object (reused across search terms)
        search_term: The keyword to search for
        date_str:    YYYY-MM-DD string for date_posted field
        debug_dir:   If set, saves rendered HTML to this directory

    Returns:
        List of job dicts
    """
    url = build_search_url(search_term)
    jobs = []

    print(f"  → {url}")

    # Navigate
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
    except PlaywrightTimeout:
        print(f"  [ERROR] Page load timed out for '{search_term}' — skipping this term")
        return jobs
    except Exception as e:
        print(f"  [ERROR] Navigation failed for '{search_term}': {e}")
        return jobs

    # Scroll to load lazy-rendered results
    for _ in range(SCROLL_COUNT):
        page.keyboard.press("End")
        page.wait_for_timeout(SCROLL_PAUSE_MS)

    # Extra settle time for React re-render after scroll
    page.wait_for_timeout(REACT_SETTLE_MS)

    # Capture rendered HTML
    html = page.content()

    # Debug: save HTML for selector inspection
    if debug_dir:
        slug = search_term.replace(" ", "_")
        debug_path = os.path.join(debug_dir, f"wellfound_debug_{slug}_{date_str.replace('-', '')}.html")
        os.makedirs(debug_dir, exist_ok=True)
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  [DEBUG] HTML saved → {debug_path}")

    # Login wall check — Wellfound shows limited results without an account
    html_lower = html.lower()
    if any(phrase in html_lower for phrase in [
        "sign in to view", "log in to continue", "create an account to view",
        "join to see", "sign up to see"
    ]):
        print(f"  [WARNING] Login wall detected — results may be limited. "
              f"Consider running with a logged-in browser session.")

    # Parse with BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Collect unique job/role links
    seen_hrefs = set()
    link_elements = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(pat in href for pat in LINK_HREF_PATTERNS) and href not in seen_hrefs:
            seen_hrefs.add(href)
            link_elements.append((href, a))

    print(f"  Found {len(link_elements)} job/role links (capping at {MAX_JOBS_PER_SEARCH})")

    for href, a_tag in link_elements[:MAX_JOBS_PER_SEARCH]:
        full_url = f"{WELLFOUND_BASE}{href}" if href.startswith("/") else href

        # Title — text of the link itself
        title = a_tag.get_text(strip=True)

        # Skip empty links, icon-only links, and navigation links
        if not title or len(title) < MIN_TITLE_LENGTH:
            continue

        # Skip obvious nav/UI links (short generic words)
        skip_words = {"jobs", "login", "sign in", "sign up", "more", "view", "see"}
        if title.lower() in skip_words:
            continue

        company_name = find_company_name(a_tag)
        location = find_location(a_tag)
        compensation = find_compensation(a_tag)

        job_id = href.rstrip("/").split("/")[-1]

        jobs.append({
            "source": "wellfound",
            "job_id": job_id,
            "title": title,
            "company": company_name,
            "location": location,
            "date_posted": date_str,
            "url": full_url,
            "description": compensation,   # compensation is the best short descriptor available
            "search_term": search_term,
        })

    print(f"  Usable jobs extracted: {len(jobs)}")
    return jobs


# ── Deduplication ────────────────────────────────────────────────────

def deduplicate(jobs: list) -> list:
    """Deduplicate by URL. First occurrence of each URL wins."""
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
    path = os.path.join(output_dir, f"raw_wellfound_{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    return path


def write_md(jobs: list, output_dir: str, date_str: str) -> str:
    """
    Write human-readable markdown summary.
    Format matches raw_jobs_YYYY-MM-DD.md produced by collect_jobs.py
    so Layers 2-7 work without modification.
    """
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"raw_wellfound_{date_str}.md")

    lines = [
        f"# Raw Wellfound Job Batch — {date_str}",
        f"",
        f"**Source:** Wellfound (wellfound.com) — startup-focused, company-verified listings, no third-party recruiters",
        f"**Total collected:** {len(jobs)}",
        f"**Status:** Unfiltered — awaiting Layer 2 global talent filter",
        f"",
        f"---",
        f"",
    ]

    for i, job in enumerate(jobs, 1):
        comp = job.get("description", "")
        lines += [
            f"## Job {i}: {job['title'] or '(no title)'}",
            f"**Source:** {job['source']}",
            f"**Company:** {job['company'] or '(not extracted — see URL)'}",
            f"**Location:** {job['location']}",
            f"**Date Posted:** {job['date_posted']}",
            f"**URL:** {job['url']}",
            f"**Search Term Match:** {job['search_term']}",
            f"",
            f"**Compensation / Notes:**",
            f"{comp or '(see listing for compensation details)'}",
            f"",
            f"---",
            f"",
        ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return path


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LinkedIn Job Intel — Wellfound Layer 1 collector")
    parser.add_argument("--config", required=True, help="Path to user config JSON")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save rendered page HTML to _temp/ for selector debugging"
    )
    args = parser.parse_args()

    config = load_config(args.config)
    search_terms = config.get("search_terms", [])
    output_path = config.get("output_path", ".")
    temp_dir = os.path.join(output_path, "_temp")
    date_str = datetime.date.today().strftime("%Y-%m-%d")

    print(f"\nLinkedIn Job Intel — Wellfound Layer 1 Collection")
    print(f"User:         {config.get('name', 'Unknown')}")
    print(f"Date:         {date_str}")
    print(f"Search terms: {search_terms}")
    print(f"Output:       {temp_dir}")
    if args.debug:
        print(f"Debug mode:   ON — rendered HTML saved to {temp_dir}")
    print()

    all_jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = context.new_page()

        # Apply stealth patches to avoid DataDome / Cloudflare bot detection
        if STEALTH_AVAILABLE:
            Stealth().apply_stealth_sync(page)
            print("Stealth mode: ON")
        else:
            print("Stealth mode: OFF (install playwright-stealth to fix DataDome blocks)")

        for term in search_terms:
            print(f"[Wellfound] '{term}'")
            jobs = scrape_search_page(
                page, term, date_str,
                debug_dir=temp_dir if args.debug else None,
            )
            all_jobs.extend(jobs)
            print(f"  Running total: {len(all_jobs)}\n")
            time.sleep(REQUEST_DELAY)

        browser.close()

    print(f"Deduplicating {len(all_jobs)} collected jobs...")
    unique = deduplicate(all_jobs)
    print(f"Unique after deduplication: {len(unique)}")

    json_path = write_json(unique, temp_dir, date_str)
    md_path = write_md(unique, temp_dir, date_str)

    print(f"\nOutput written:")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")
    print(f"\nWellfound Layer 1 complete.")
    print(f"Hand the MD file to Claude to run Layer 2 filtering.")


if __name__ == "__main__":
    main()
