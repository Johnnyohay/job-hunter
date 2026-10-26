# Job Agent

My job-application agent. It runs on my Mac through **Claude Code on my existing subscription**: no API keys, no cloud costs. Every morning it:

1. **Finds roles**: pulls every open job from the companies in my *Companies to Watch* sheet (Greenhouse, Lever and Ashby boards) plus any posting I paste into *Target Positions*.
2. **Screens them**: a keyword and location filter (`config/search.yaml`), then Claude scores each new role 0-100 against my CV, LinkedIn PDF, *About Me* notes and *Job Preferences*.
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

Each run scores up to 25 new jobs (`maxScoredPerRun` in `config/search.yaml`) and prepares up to 5, which counts against my Claude plan's usage limits. Raise or lower those numbers to match the plan.
