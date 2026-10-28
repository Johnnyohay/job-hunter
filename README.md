# Job Hunter

My job-search service. Everything runs on my Mac, on my Claude subscription and public data: no API keys, no cloud costs. It has three workers:

| Worker | When | What it does | Where |
|---|---|---|---|
| **Applicant** | Daily, 8:00 | Finds new roles at my target companies, scores them against my profile, finds hiring managers, drafts materials, tracks everything in my Application Tracker sheet | the repo root (`src/`, `config/`, `.claude/commands/daily.md`) |
| **Market DB** | Daily, 7:10 | Builds a SQLite database of public labor-market data for Boston and the East Coast (BLS, Census, job postings) with a dashboard and CSV exports | `workers/market-db/` (its own [README](workers/market-db/README.md); Python, standard library) |
| **Targeting map** | Weekly | Claude desktop scheduled task that refreshes my job-targeting map with current hiring trends | `workers/targeting-map/SKILL.md` (hard-linked to the task in `~/Claude/Scheduled/`, so editing either edits both) |

Schedules: `npm run schedule` (Applicant) and `npm run schedule:market-db` (Market DB) install the launchd jobs; the targeting map is scheduled in the Claude desktop app. The market DB's data (`jobmarket.db`, exports, about 900 MB) stays local and out of git.

## Applicant

Every morning it:

1. **Finds roles**: pulls every open job from the companies in my *Companies to Watch* sheet (Greenhouse, Lever and Ashby boards) plus any posting I paste into *Target Positions*.
2. **Screens them**: a keyword and location filter (`config/search.ts`), then Claude scores each new role 0-100 against my CV, LinkedIn PDF, *About Me* notes and *Job Preferences*.
3. **Prepares the best ones**: for the top matches (up to my daily limit) it finds the likely **hiring manager** and their LinkedIn profile through web search, then drafts a cover letter, CV tweaks, answers to likely questions and a short LinkedIn note, saved as a Google Doc in `Applications/`.
4. **Tracks everything** in the *Application Tracker* sheet.

Applying stays supervised: I set a row's Status to **Approved**, run `npm run apply`, and it opens each form in Chrome, pre-fills it and uploads my CV. I review and click Submit myself, and the tracker is updated.

## How it fits together

```
npm run fetch          Node: profile from Drive + new jobs from the boards  -> .state/
/daily (Claude Code)   scores jobs, finds hiring managers, drafts materials -> .state/results.json, .state/materials/
npm run record         Node: materials docs to Drive, rows to the tracker
```

`.claude/commands/daily.md` is the whole pipeline (it runs fetch and record itself); `scripts/run-daily.sh` runs it headless with `claude -p "/daily"`.

Drive access goes through a small **Apps Script bridge** (`apps-script/Code.gs`) deployed from my own Google account: free, no Google Cloud project. It has least-privilege access, enforced by Google: **read-only** on my Drive (`drive.readonly`, so it can never change or delete my files), and edit rights only on files it created itself (`drive.file`): its own *Application Tracker* and *Applications* folder. It also only accepts requests carrying the token in `.env`, and only reads inside the Job Application Agent folder.

## Built to last

- **Job boards are data, not code.** `config/ats.ts` describes each ATS: its public endpoint and where each field sits in its response. Following an API change or adding a new ATS means editing that file. If a response stops matching, the run names the missing field instead of silently writing blanks.
- **The code moves data; Claude interprets it.** Nothing parses pay, workplace or locations with patterns. Claude reads each posting and records the facts (workplace, primary place with coordinates, pay as numbers, plus the text it came from), so changes in how postings are worded don't break anything. `src/facts.ts` checks those facts before they reach the tracker.
- **Almost no dependencies.** Node (22.18+) runs the TypeScript directly, and everything else uses Node's built-ins (`fetch`, `fs`). The one runtime dependency is Playwright, used only by `npm run apply`. TypeScript is a dev dependency, used only for `npm run typecheck`.

## Tracker columns

Typed for analysis: `Found`, `Applied On` and `Last Update` are dates; `Fit`, `# Locations`, `Comp Min` and `Comp Max` (annual, in `Currency`) are numbers; `Latitude` and `Longitude` are the primary place's coordinates (blank for remote jobs, whose `Country` is where they hire). `Workplace` is one of Remote, Hybrid, Onsite, Flexible or Unknown. `Locations (as posted)` and `Comp (as posted)` keep the original text. `npm run tracker:format` reapplies the layout and moves rows into new columns by name after a schema change.

## Ground rules built in

- It never invents facts. Everything about me comes from my Drive docs; anything missing is listed under "Needs from you".
- It never scrapes LinkedIn or contacts anyone. Hiring managers come from public web search results, and the LinkedIn note is for me to send.
- It never submits an application on its own.

## Google Drive: the "Job Application Agent" folder

| Item | What it is |
|---|---|
| `Profile/CV.pdf` | The CV it reads and uploads (any PDF without "linkedin" in the name; a Google Doc named `CV` also works) |
| `Profile/LinkedIn.pdf` | LinkedIn → profile → More → Save to PDF |
| `Profile/About Me (beyond the CV)` | Work authorization, salary, start date, stories: whatever forms ask that a CV doesn't say |
| `Job Preferences` | Target roles, locations, comp, deal-breakers, LinkedIn URL, minimum fit score and daily limit |
| `Target Positions` | Paste job URLs here to have them evaluated directly |
| `Companies to Watch` | Company, ATS (`greenhouse` / `lever` / `ashby`), board name (the slug in the careers URL), Active |
| `Application Tracker` | Everything the agent finds and does (created by the bridge; its id is in `.env`) |
| `Applications/` | One materials doc per prepared role (created by the bridge; its id is in `.env`) |

Tracker statuses: `Not a fit` (below 50 or a deal-breaker), `Possible fit` (50 to the minimum fit; no materials, approve it if you want it) → `Shortlisted` → `Ready for review` → **`Approved`** (set by me) → `Applied` / `Skipped`. My own statuses (Interview, Rejected, Offer...) are left alone.

## Setup (one time)

```bash
npm install
cp .env.example .env
npm run check                     # tests the job boards and the filter; needs nothing
npx @google/clasp login           # once; also turn on the Apps Script API at script.google.com/home/usersettings
npm run bridge:deploy             # deploys the bridge (re-run after editing apps-script/; keeps the same URL)
                                  # then authorize once: open the script, Run > doGet, Allow
npm run bridge -- <web app URL>   # saves the URL, tests it, creates the agent's own tracker and Applications folder
npm run fetch -- --dry-run        # lists what would be scored; writes nothing
```

Then, from this folder:

```bash
claude "/daily"                   # first run, watched
npm run schedule                  # every day at 8:00 (npm run schedule -- 7 for 7:00; -- --remove to stop)
npm run apply                     # supervised applying for Approved rows (uses installed Chrome)
```

The schedule uses macOS launchd: if the Mac is asleep at 8:00, the run starts when it wakes. Logs go to `logs/`.

## Usage

Each run scores up to 25 new jobs (`maxScoredPerRun` in `config/search.ts`) and prepares up to 5, which counts against my Claude plan's usage limits. Raise or lower those numbers to match the plan.
