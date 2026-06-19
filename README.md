# 🔍 Automated Job Discovery & Filtering Pipeline | Python | Career Services

## Executive Summary

Manually re-searching multiple remote job boards every day for keyword-matched, location-eligible roles doesn't scale — especially when doing it for more than one person with a different skill profile. This project is a Python pipeline that collects listings daily from four independent sources (LinkedIn, Wellfound, We Work Remotely, Work at a Startup), filters them against a per-user JSON profile, and emails a ranked digest — unattended, via Windows Task Scheduler. It's multi-tenant by design: a second user in a completely different niche (HR/Talent Acquisition vs. my own BI/Analytics focus) runs on the identical codebase with zero code changes, just a separate config file. Over 30+ consecutive automated daily runs it has taken thousands of raw daily listings down to a small, ranked, relevant shortlist per user, per day.

---

## 📌 Business Problem

Each job platform formats listings differently, none filter well for "remote and genuinely open to candidates outside the US/EU," and repeating that search by hand across 4+ sites daily — for every person you're mentoring — is time that should go to higher-value mentoring work instead.

---

## 🧩 Methodology

Layered pipeline: (1) source-specific collectors — LinkedIn jobs-guest API, Wellfound/Work at a Startup via Playwright, We Work Remotely via RSS; (2) a rule-based filter enforcing a strict remote/global-talent test; (3) a per-user JSON config drives keyword, sector, and location targeting with no code changes; (4) SMTP digest delivery; (5) Windows Task Scheduler for unattended daily runs. New users onboard via one config file.

---

## 🛠️ Skills Demonstrated

- **Python:** `requests` + BeautifulSoup (HTML scraping), Playwright (JS-rendered site automation), `feedparser` (RSS), `smtplib` (email automation), `argparse`, config-driven architecture
- **Automation:** Windows Task Scheduler, batch scripting, unattended daily execution, logging
- **AI-Assisted Workflow Orchestration:** Claude Desktop connected via MCP (Model Context Protocol) drives the manual filtering, intake, and tracking layers — Claude reads the daily raw output and writes structured records, working alongside the unattended Python automation rather than replacing it
- **Project Architecture:** clean, automation-friendly folder structure (`config/`, `scripts/`, `docs/`) that keeps unattended automation, AI-assisted review, and documentation cleanly separated — built so a new user can onboard without touching code
- **Data pipeline design:** multi-source ingestion, layered filter/transform stages, multi-tenant configuration pattern
- **Systems thinking:** turned a personal time-cost problem into a reusable, configurable tool for multiple users across different professional domains

---

## 📊 Results & Recommendations

- 30+ consecutive days of automated daily collection across 4 independent sources with no missed runs
- Multi-tenant from the start — onboarded a second user in a different professional niche using the same code, config-only, validating it isn't hard-coded to one person's search
- **Recommendation:** the config-driven filter pattern generalizes beyond job search (grant calls, RFPs, leads) — same architecture, swap the source collectors
- **Recommendation:** as listing volume grows, a lightweight NLP classifier could reduce manual review further than the current rule-based filter
- **Recommendation:** a small web dashboard would beat email for browsing match history over time

---

## 🚀 Next Steps

- Build out the 7-day rolling recommendation/report layer fully
- Add a funded-company signal feed to help prioritize which companies are actively hiring
- Onboard more users to stress-test the multi-tenant config pattern
- ⚠️ Known limitation: source sites change HTML structure without notice and silently break collectors — worth adding schema-drift detection
