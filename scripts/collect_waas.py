"""
collect_waas.py — Layer 1: Work at a Startup (YC) job collection
LinkedIn Job Intel — Anthony Chilaka

Source:   Work at a Startup / workatastartup.com — Y Combinator's official job board.
          All companies are YC-vetted. No third-party recruiters. Higher signal-to-noise
          than LinkedIn for startup-stage remote roles. Only actively hiring YC companies.
Method:   Playwright (sync API) — page is React-rendered, requests will NOT work.

FIRST-TIME SETUP (one-time, run in terminal):
  pip install playwright beautifulsoup4
  playwright install chromium
  (If already installed for collect_wellfound.py — no repeat setup needed.)

Usage:
  python collect_waas.py --config ../config/anthony.json
  python collect_waas.py --config ../config/anthony.json --debug
  python collect_waas.py --config ../config/mentees/user2.json

Output (written to config["output_path"]/_temp/):
  raw_waas_YYYY-MM-DD.json   — machine-readable, full detail
  raw_waas_YYYY-MM-DD.md     — human-readable, for Claude Layer 2

If selectors break after a site redesign:
  1. Run with --debug to save the rendered page HTML to _temp/
  2. Open the HTML file, inspect job card structure
  3. Update WAAS_JOB_LINK_PATTERN and WAAS_COMPANY_LINK_PATTERN below

Filter approach:
  The WAAS search URL accepts a ?query= parameter but the site renders all jobs
  and filters client-side. This script fetches each search term as a separate
  query URL — each URL triggers a server-side filter for that term. Results are
  merged and deduplicated by URL across all search terms.

  IMPORTANT — niche title filter:
  WAAS search matches on company profiles, not just job titles. A query for
  "business intelligence" returns ALL open roles at companies with BI-adjacent
  work — including Engineering, Design, Finance, Legal, etc. This script applies
  a post-collection title filter (NICHE_TITLE_KEYWORDS) to discard non-analytics
  roles before writing output. Only jobs whose title contains at least one niche
  keyword are kept.
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
    print("[WARNING] playwright-stealth not installed — site may block the request.")
    print("  Run: pip install playwright-stealth")


# ── Niche title filter ─────────────────────────────────────────────────
#
# WAAS returns ALL open roles at matching companies, not just analytics roles.
# This filter keeps only jobs whose title contains at least one of these keywords.
# Add terms here if relevant roles are being dropped; remove if noise increases.
#
NICHE_TITLE_KEYWORDS = [
    "analyst",
    "analytics",
    "analysis",
    "business intelligence",
    "bi developer",
    "bi analyst",
    "bi engineer",
    "power bi",
    "data analyst",
    "data analysis",
    "data engineer",          # keep — often overlaps with BI pipeline work
    "data scientist",         # keep — sometimes posted alongside analyst roles
    "reporting",
    "dashboard",
    "insights",
    "web analytics",
    "marketing analytics",
    "product analytics",
    "growth analyst",
    "operations analyst",
    "revenue analyst",
    "financial analyst",
    "ecommerce analyst",
    "e-commerce analyst",
    "crm analyst",
    "looker",
    "tableau",
    "sql analyst",
]


def is_niche_title(title: str) -> bool:
    """Return True if the job title contains at least one niche keyword."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in NICHE_TITLE_KEYWORDS)


# ── Selectors — update here if WAAS redesigns ───────────────────────────

WAAS_BASE = "https://www.workatastartup.com"
WAAS_JOBS = f"{WAAS_BASE}/jobs"

# Job detail links on WAAS follow the pattern /jobs/{job-id}
# Company profile links follow /companies/{slug}
# Update these if the URL structure changes after a redesign.
WAAS_JOB_LINK_PATTERN = "/jobs/"
WAAS_COMPANY_LINK_PATTERN = "/companies/"

# Stage labels that WAAS shows on job cards — used to extract company stage
# e.g. "Series A", "Seed", "Series B", "Growth"
STAGE_PATTERN = re.compile(
    r"\b(Seed|Pre-Seed|Series [A-F]|Growth|Public|Acquired)\b", re.IGNORECASE
)

# Compensation range pattern (same style as Wellfound)
SALARY_PATTERN = re.compile(r"\$[\d,]+[kK]?\s*[–\-—]\s*\$[\d,]+[kK]?")


# ── Constants ──────────────────────────────────────────────────────────

REQUEST_DELAY = 4          # Seconds between search term requests
SCROLL_COUNT = 5           # Scrolls to trigger lazy-loading
SCROLL_PAUSE_MS = 1500     # ms between each scroll
REACT_SETTLE_MS = 2500     # ms extra after final scroll for React re-render
PAGE_LOAD_TIMEOUT = 35000  # ms
MAX_JOBS_PER_SEARCH = 50   # Cap per search term
MIN_TITLE_LENGTH = 4


# ── Config loader ──────────────────────────────────────────────────────────

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── URL builder ────────────────────────────────────────────────────────────────

def build_search_url(search_term: str) -> str:
    """
    Build a WAAS search URL for the given term with remote filter active.
    WAAS accepts ?query= for keyword search and ?remote=true for remote-only.
    """
    return f"{WAAS_JOBS}?{urlencode({'query': search_term, 'remote': 'true'})}"


# ── DOM helpers ────────────────────────────────────────────────────────────────

def find_company_name(a_tag) -> str:
    """
    Walk up from a job link to find the nearest company link in the same card.
    WAAS groups roles under company cards — company name is in an <a href="/companies/..."> tag.
    """
    node = a_tag.parent
    for _ in range(12):
        if node is None:
            break
        company_link = node.find(
            "a", href=lambda h: h and WAAS_COMPANY_LINK_PATTERN in h
        )
        if company_link:
            name = company_link.get_text(strip=True)
            if name and len(name) >= 2:
                return name
        node = node.parent
    return ""


def find_stage(a_tag) -> str:
    """
    Look for a YC funding stage label (Seed, Series A, etc.) near the job link.
    WAAS typically shows this alongside the company name in the card.
    Returns the stage string or empty string.
    """
    node = a_tag.parent
    for _ in range(10):
        if node is None:
            break
        text = node.get_text(separator=" ", strip=True)
        match = STAGE_PATTERN.search(text)
        if match:
            return match.group()
        node = node.parent
    return ""


def find_compensation(a_tag) -> str:
    """Look for a salary range near the job link."""
    node = a_tag.parent
    for _ in range(8):
        if node is None:
            break
        text = node.get_text(separator=" ", strip=True)
        salary_match = SALARY_PATTERN.search(text)
        if salary_match:
            return f"Salary: {salary_match.group()}"
        node = node.parent
    return ""


# ── Scraper ─────────────────────────────────────────────────────────────────

def scrape_search_page(page, search_term: str, date_str: str,
                       debug_dir: str = None) -> list:
    """
    Navigate to a WAAS search results page and extract job listings.

    Strategy:
      1. Load page with Playwright (handles React rendering)
      2. Scroll to trigger lazy-loading of additional results
      3. Capture rendered HTML and parse with BeautifulSoup
      4. Find job links by href pattern (/jobs/)
      5. For each link, walk the DOM upward for company name, stage, and compensation

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

    print(f"  -> {url}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
    except PlaywrightTimeout:
        print(f"  [ERROR] Page load timed out for '{search_term}' — skipping")
        return jobs
    except Exception as e:
        print(f"  [ERROR] Navigation failed for '{search_term}': {e}")
        return jobs

    # Scroll to load lazy-rendered results
    for _ in range(SCROLL_COUNT):
        page.keyboard.press("End")
        page.wait_for_timeout(SCROLL_PAUSE_MS)

    # Extra settle time for React re-render
    page.wait_for_timeout(REACT_SETTLE_MS)

    html = page.content()

    # Debug: save rendered HTML for selector inspection
    if debug_dir:
        slug = search_term.replace(" ", "_")
        debug_path = os.path.join(debug_dir, f"waas_debug_{slug}_{date_str.replace('-', '')}.html")
        os.makedirs(debug_dir, exist_ok=True)
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  [DEBUG] HTML saved -> {debug_path}")

    # Login wall check — WAAS requires an account for some views
    html_lower = html.lower()
    if any(phrase in html_lower for phrase in [
        "sign in", "log in to continue", "create an account",
        "join y combinator", "apply to yc"
    ]):
        # WAAS always shows some of these phrases in the nav — only warn if
        # the page body looks like it's blocking content
        if "no jobs found" not in html_lower and len(html) < 10000:
            print(f"  [WARNING] Page content appears limited — WAAS may require login for full results.")

    soup = BeautifulSoup(html, "html.parser")

    # Collect unique job links matching the /jobs/ pattern
    # WAAS also has navigation links like /jobs — skip those with a trailing digit check
    seen_hrefs = set()
    link_elements = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Must contain /jobs/ and be followed by a job ID segment (not just /jobs alone)
        if (WAAS_JOB_LINK_PATTERN in href
                and href != "/jobs"
                and href != "/jobs/"
                and href not in seen_hrefs):
            seen_hrefs.add(href)
            link_elements.append((href, a))

    print(f"  Found {len(link_elements)} job links (capping at {MAX_JOBS_PER_SEARCH})")

    for href, a_tag in link_elements[:MAX_JOBS_PER_SEARCH]:
        full_url = f"{WAAS_BASE}{href}" if href.startswith("/") else href

        title = a_tag.get_text(strip=True)

        # Skip empty, icon-only, or navigation links
        if not title or len(title) < MIN_TITLE_LENGTH:
            continue

        skip_words = {"jobs", "login", "sign in", "sign up", "apply", "more"}
        if title.lower() in skip_words:
            continue

        company_name = find_company_name(a_tag)
        stage = find_stage(a_tag)
        compensation = find_compensation(a_tag)

        # Build a description string from available metadata
        description_parts = []
        if stage:
            description_parts.append(f"Stage: {stage}")
        if compensation:
            description_parts.append(compensation)
        description = " | ".join(description_parts)

        job_id = href.rstrip("/").split("/")[-1]

        jobs.append({
            "source": "workatastartup",
            "job_id": job_id,
            "title": title,
            "company": company_name,
            "location": "Remote",
            "date_posted": date_str,
            "url": full_url,
            "description": description,
            "search_term": search_term,
            "stage": stage,
        })

    print(f"  Usable jobs extracted: {len(jobs)}")
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
    path = os.path.join(output_dir, f"raw_waas_{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    return path


def write_md(jobs: list, output_dir: str, date_str: str) -> str:
    """
    Write human-readable markdown summary.
    Format matches raw_jobs_YYYY-MM-DD.md so Layers 2–7 work without modification.
    """
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"raw_waas_{date_str}.md")

    lines = [
        f"# Raw Work at a Startup (YC) Job Batch — {date_str}",
        f"",
        f"**Source:** Work at a Startup / workatastartup.com — Y Combinator vetted companies only",
        f"**Total collected:** {len(jobs)}",
        f"**Status:** Unfiltered — awaiting Layer 2 global talent filter",
        f"",
        f"---",
        f"",
    ]

    for i, job in enumerate(jobs, 1):
        stage_label = f" [{job['stage']}]" if job.get("stage") else ""
        lines += [
            f"## Job {i}: {job['title'] or '(no title)'}",
            f"**Source:** {job['source']}{stage_label}",
            f"**Company:** {job['company'] or '(not extracted — see URL)'}",
            f"**Location:** {job['location']}",
            f"**Date Posted:** {job['date_posted']}",
            f"**URL:** {job['url']}",
            f"**Search Term Match:** {job['search_term']}",
            f"",
            f"**Description / Stage / Comp:**",
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
        description="LinkedIn Job Intel — Work at a Startup (YC) Layer 1 collector"
    )
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

    print(f"\nLinkedIn Job Intel — Work at a Startup (YC) Layer 1 Collection")
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

        # Apply stealth patches to avoid bot detection
        if STEALTH_AVAILABLE:
            Stealth().apply_stealth_sync(page)
            print("Stealth mode: ON")
        else:
            print("Stealth mode: OFF (install playwright-stealth to fix bot blocks)")

        for term in search_terms:
            print(f"[WAAS] '{term}'")
            jobs = scrape_search_page(
                page, term, date_str,
                debug_dir=temp_dir if args.debug else None,
            )
            all_jobs.extend(jobs)
            print(f"  Running total: {len(all_jobs)}\n")
            time.sleep(REQUEST_DELAY)

        browser.close()

    # Apply niche title filter — discard Engineering, Design, Finance etc.
    # WAAS returns all open roles at matching companies, not just analytics roles.
    pre_filter_count = len(all_jobs)
    all_jobs = [j for j in all_jobs if is_niche_title(j.get("title", ""))]
    discarded = pre_filter_count - len(all_jobs)
    print(f"Niche title filter: kept {len(all_jobs)} of {pre_filter_count} "
          f"({discarded} non-analytics roles discarded)")

    print(f"Deduplicating {len(all_jobs)} niche-filtered jobs...")
    unique = deduplicate(all_jobs)
    print(f"Unique after deduplication: {len(unique)}")

    json_path = write_json(unique, temp_dir, date_str)
    md_path = write_md(unique, temp_dir, date_str)

    print(f"\nOutput written:")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")
    print(f"\nWork at a Startup Layer 1 complete.")

    if len(unique) == 0:
        print("\n[NOTE] Zero niche-filtered jobs collected.")
        print("  Possible causes:")
        print("  1. WAAS requires login to see full results — try running with a")
        print("     saved browser session.")
        print("  2. No analytics/BI roles open at matching YC companies today (most common).")
        print("  3. Search terms don't match WAAS company profiles — try broader terms.")
        print("  4. Selectors changed after a WAAS redesign — run with --debug and inspect the HTML.")
        print("  To see ALL collected titles before filtering, add --debug and check the HTML,")
        print("  or temporarily comment out the is_niche_title() filter in main().")

    print(f"\nHand the MD file to Claude to run Layer 2 filtering.")


if __name__ == "__main__":
    main()
