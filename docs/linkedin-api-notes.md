# Source Research Notes

**Last Updated:** 2026-05-23

---

## Jobs-Guest API (Source A)

LinkedIn exposes a public guest endpoint that serves job listings to non-logged-in visitors.

**Base URL:**
```
https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
```

**Job detail URL:**
```
https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}
```

**Key parameters:**

| Parameter | Value | Meaning |
|---|---|---|
| `keywords` | e.g. "Power BI" | Search term |
| `f_WT` | `2` | Remote only |
| `f_TPR` | `r86400` | Posted in last 24 hours (86400 seconds) |
| `start` | `0`, `25`, `50`... | Pagination offset |

**No authentication required.** This endpoint is served to non-logged-in visitors and does not require cookies or a LinkedIn account.

**ToS note:** LinkedIn's User Agreement prohibits scraping. However, the hiQ Labs v. LinkedIn ruling (9th Circuit, affirmed) established that scraping publicly accessible data does not violate the Computer Fraud and Abuse Act. No LinkedIn account is used or at risk. Risk is limited to ToS violation, not account ban or legal liability for personal use.

**Stability:** Source sites periodically change the HTML structure of job cards. If a collector stops extracting titles or descriptions, the HTML parsing will need updating. Check the CSS classes and tag structure and update the BeautifulSoup selectors accordingly.

---

## Feed Post Search (Source B)

Informal "we're hiring" feed posts are not available via the jobs-guest API. They are indexed by Google and accessible via site: search.

**Query pattern:**
```
site:linkedin.com "hiring" "remote" "[search term]" after:YYYY-MM-DD
```

**Limitations:**
- Google does not guarantee indexing of all posts
- Results are delayed by Google's crawl frequency
- Feed posts have less structured data than formal job listings (no standard title/company/skills fields)
- Company name is often not extracted cleanly — inferred from title and snippet

**Improvement opportunity:** If Google returns thin results, try Bing's `site:` operator as an alternative. Bing sometimes indexes more recently than Google.

---

## RSS Feeds — Discontinued

Upwork RSS feeds were discontinued August 20, 2024. LinkedIn RSS feeds for job searches were similarly discontinued. Do not attempt to use RSS-based approaches for either platform.

---

## Official LinkedIn API — Not applicable

LinkedIn's official Talent API is restricted to certified partner companies (incorporated entities). Not available to individual developers or freelancers. No application path for personal use.
