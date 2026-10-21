# Job Agent

My job-application agent. Every morning it:

1. **Finds roles**: pulls every open job from the companies in my *Companies to Watch* sheet (Greenhouse, Lever and Ashby boards) plus any specific posting I paste into *Target Positions*.
2. **Screens them**: a cheap keyword and location filter (`config/search.yaml`), then Claude scores each new role 0-100 against my CV, LinkedIn PDF, *About Me* notes and *Job Preferences*.
3. **Prepares the best ones**: for the top matches (up to my daily limit) it finds the likely **hiring manager** and their LinkedIn profile, then drafts a cover letter, CV tweaks, answers to likely questions and a short LinkedIn note. All of it goes into a Google Doc in `Applications/`.
4. **Tracks everything** in the *Application Tracker* sheet.

Applying stays supervised: I set a row's Status to **Approved**, run `npm run apply`, and it opens each form in Chrome, pre-fills it and uploads my CV. I review it and click Submit myself, and the tracker is updated.

## Ground rules built in

- It never invents facts. Everything about me comes from my Drive docs; anything missing is listed under "Needs from you".
- It never scrapes LinkedIn or contacts anyone. Hiring managers are found through Claude's web search of public results, and the LinkedIn note is for me to send.
- It never submits an application on its own.

## Google Drive: the "Job Application Agent" folder

| Item | What it is |
|---|---|
| `Profile/CV.pdf` | The CV it reads and uploads (a Google Doc named `CV` also works) |
| `Profile/LinkedIn.pdf` | LinkedIn → profile → More → Save to PDF |
| `Profile/About Me (beyond the CV)` | Work authorization, salary, start date, stories: whatever forms ask that a CV doesn't say |
| `Job Preferences` | Target roles, locations, comp, deal-breakers, LinkedIn URL, minimum fit score and daily limit |
| `Target Positions` | Paste job URLs here to have them evaluated directly |
| `Companies to Watch` | Company, ATS (`greenhouse` / `lever` / `ashby`), board name (the slug in the careers URL), Active |
| `Application Tracker` | Everything the agent finds and does |
| `Applications/` | One materials doc per prepared role |

Tracker statuses: `Not a fit` → `Shortlisted` → `Ready for review` → **`Approved`** (set by me) → `Applied` / `Skipped`. My own statuses (Interview, Rejected, Offer...) are left alone.

## Setup

```bash
npm install
cp .env.example .env              # fill in the values below
npm run check                     # no credentials needed: tests the job boards and the filter
npm run auth:google               # prints GOOGLE_REFRESH_TOKEN
npm run daily -- --dry-run        # lists what it would score, writes nothing
npm run daily                     # the real run
npm run apply                     # supervised applying for Approved rows (uses installed Chrome)
```

**Google credentials (one time):** in [Google Cloud Console](https://console.cloud.google.com/), create a project, enable the **Google Drive API** and **Google Sheets API**, configure the OAuth consent screen (External, add myself as a test user, then **Publish app**; in Testing mode refresh tokens expire after 7 days), and create an **OAuth client ID** of type *Desktop app*. Put the client ID and secret in `.env`, then run `npm run auth:google`.

**GitHub Actions:** add secrets `ANTHROPIC_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, and a variable `JOB_AGENT_FOLDER_ID`. The workflow runs daily at 12:00 UTC and can be started manually from the Actions tab (with a dry-run option).

## Cost

Claude Opus 5.5. My documents are prompt-cached, so each scored job costs about 1-2¢, and each prepared application (hiring-manager search plus materials) costs roughly 15-30¢. With the defaults (up to 60 scored and 5 prepared per day), that's about $1-2 a day.
