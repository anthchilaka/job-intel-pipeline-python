# Setup Guide — Job Intel Pipeline

**Version:** 1.0

---

## Prerequisites

- Python 3.10 or later installed on your computer
- Google Chrome (for browsing job sites manually — not required for the scripts)
- A Gmail account you will create as the dedicated product sender

---

## Step 1 — Install Python dependencies

Open a terminal and run:

```
pip install requests beautifulsoup4
```

That is all that is required. Both libraries are free and widely available.

---

## Step 2 — Create the product Gmail account

1. Go to https://accounts.google.com/signup
2. Create a new Gmail account — recommended name: `jobintelpipeline@gmail.com` or similar
3. Once created, go to **Manage your Google Account → Security**
4. Enable **2-Step Verification** (required for App Passwords)
5. After enabling 2-Step Verification, go to **Security → App Passwords**
6. Select **App: Mail** and **Device: Windows Computer**
7. Google will generate a 16-character App Password — copy it

---

## Step 3 — Update sender.json

Copy `config\sender.json.example` to `config\sender.json` and replace the
placeholder values with your own:

```json
{
  "sender_email": "YOUR_NEW_GMAIL@gmail.com",
  "sender_password": "YOUR_16_CHAR_APP_PASSWORD",
  "smtp_server": "smtp.gmail.com",
  "smtp_port": 587
}
```

**Important:** Use the App Password from Step 2, not your Gmail login password.

---

## Step 4 — Verify your config file

Copy `config\anthony.json.example` to your own config file and confirm:
- `notify_to` is your notification email address
- `output_path` points to your output folder
- `search_terms` matches the roles you want to track

---

## Step 5 — First test run (manual)

Open a terminal, navigate to the scripts folder, and run:

```
cd scripts
python collect_jobs.py --config ../config/your_config.json
```

Check the output folder defined in `output_path` — you should see:
- `raw_jobs_YYYY-MM-DD.json`
- `raw_jobs_YYYY-MM-DD.md`

Open the `.md` file and review the raw collected jobs. Then bring the file
to a Claude session for filtering and tracking.

---

## Step 6 — Test the notification

Once `sender.json` is updated with real credentials, run:

```
python notify.py --config ../config/your_config.json --jobs-file path/to/filtered_jobs.json
```

Check the inbox configured as `notify_to` in your config — you should
receive the notification email within seconds.

---

## Step 7 — Schedule the daily task

Two files have been created for this step:

- `scripts\run_daily.bat` — the script Windows will execute each morning
- `scripts\linkedin_job_intel_scheduler.xml` — Task Scheduler import file (5:00 AM daily)

**To import the scheduled task:**

1. Press `Win + S`, search for **Task Scheduler**, and open it
2. In the right-hand panel, click **Import Task...**
3. Navigate to `scripts\linkedin_job_intel_scheduler.xml` and open it
4. The task details will appear — confirm the Name
5. Click **OK** — you will be prompted for your Windows password (required for scheduling)
6. The task now appears in **Task Scheduler Library**

**To verify the task is registered:**

1. In Task Scheduler Library, find the imported task
2. Right-click → **Run** to trigger it immediately (test run)
3. Check your log file — you should see a timestamped entry and `completed successfully`

**What gets automated:**

| Layer | Automated? | Notes |
|---|---|---|
| Collection — collect_jobs.py | ✅ Yes — 5:00 AM daily | Output saved to your output folder |
| Filtering | ❌ Manual — Claude Desktop (MCP) | Bring the raw jobs file to Claude |
| Notification — notify.py | ❌ Manual — run after filtering | `python notify.py --config ../config/your_config.json --jobs-file path/to/filtered_jobs.json` |
| Intake & tracking | ❌ Manual — Claude Desktop (MCP) | Claude writes structured intake + tracker files |

**A typical daily routine once scheduled:**

1. Wake up — raw jobs have been collected since 5 AM
2. Open Claude Desktop — point it at today's raw jobs file
3. Claude filters, you review, Claude writes intake and trackers
4. Run `notify.py` manually after filtering is done

---

## Adding a Second User

See `docs\onboarding.md` for the full onboarding flow.

---

## Troubleshooting

| Error | Likely cause | Fix |
|---|---|---|
| `SMTPAuthenticationError` | Wrong App Password or 2FA not enabled | Re-generate App Password in Google Account settings |
| No jobs collected | Source site changed their HTML structure | Update the relevant collector's selectors |
| Google search returns no results | Rate limiting or query change | Increase `REQUEST_DELAY` in scripts, or wait 30 minutes |
| `FileNotFoundError` on output path | Path in config JSON is incorrect | Check `output_path` in your config JSON |
