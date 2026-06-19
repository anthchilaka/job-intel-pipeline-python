# Mentee Onboarding Guide — LinkedIn Job Intel

**Last Updated:** 2026-05-23

---

## Overview

Each mentee gets their own config file and their own output path within the Freelance Profile project. The pipeline logic is shared. The profile context and notification address are theirs.

Claude guides the onboarding in a Cowork session using AskUserQuestion to collect all required details before creating any files.

---

## What gets created per mentee

| File / Folder | Path | Purpose |
|---|---|---|
| Mentee config | `config\mentees\[name].json` | Profile, search terms, notification email, output path |
| Job posts folder | `OUTPUTS\Freelance Profile\mentees\[name]\job-posts\` | Daily intake files land here |
| Knowledge base folder | `OUTPUTS\Freelance Profile\mentees\[name]\knowledge-base\` | Tracker files for this mentee |

---

## Onboarding checklist

Claude will use AskUserQuestion to collect:

- [ ] Mentee name or identifier (used as folder name and config filename — lowercase, no spaces)
- [ ] Notification email address (where they want to receive daily job alerts)
- [ ] Tools they use (e.g. Power BI, Tableau, SQL, Python)
- [ ] Sectors they work in (e.g. fintech, healthcare, retail)
- [ ] Target niches (e.g. Business Analytics, Web Analytics)
- [ ] Search terms (defaults: "business intelligence", "web analytics", "Power BI" — override if different)

---

## Config template

Once details are collected, Claude creates `config\mentees\[name].json`:

```json
{
  "name": "[Mentee Name]",
  "notify_to": "[mentee email address]",
  "output_path": "/path/to/your/output/folder/mentees/[name]",
  "search_terms": ["business intelligence", "web analytics", "Power BI"],
  "niches": ["Business Analytics", "Web Analytics"],
  "tools": ["[tool1]", "[tool2]"],
  "sectors": ["[sector1]", "[sector2]"],
  "global_filter": "strict",
  "collection_window_hours": 24,
  "recommendation_day_threshold": 7
}
```

---

## Running the pipeline for a mentee

All three scripts accept a `--config` argument. Point to the mentee's config file:

```
python collect_jobs.py --config ../config/mentees/user2.json
python notify.py --config ../config/mentees/user2.json --jobs-file path/to/filtered.json
```

Intake files land in the mentee's own `job-posts\` folder. Trackers update independently.

---

## 7-day recommendation cycle for mentees

Same trigger as Anthony: after 7 days of data, Claude notifies Anthony (not the mentee directly). Anthony reviews and confirms before delivery. Recommendations are personalised to the mentee's profile context.
