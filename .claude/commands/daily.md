---
description: Daily job-agent run - fetch new jobs, score them against my profile, find hiring managers, draft materials, record to the tracker
---

You are running my daily job search. Work through the steps in order without asking me anything: this usually runs unattended. If a step fails, say what failed in the final summary and stop rather than improvising around it.

## Ground rules

- Facts about me come only from the files in `.state/profile/`. Never invent or inflate experience, metrics, titles, dates, skills, credentials or work authorization. If something an application needs is missing, list it under `needs_from_you` instead of guessing.
- Never contact anyone, never submit an application, never log in to LinkedIn or fetch linkedin.com pages. Hiring managers are found through web search results only.
- Write in plain, confident, specific language. No buzzwords and no flattery of the company.

## 1. Fetch

Run `npm run fetch`. It writes:
- `.state/profile/`: `CV.pdf` (or `CV.txt`), `LinkedIn.pdf` (if present), `about-me.txt`, `job-preferences.txt`
- `.state/candidates.json`: the new jobs to evaluate
- `.state/run.json`: `minFit` and `maxTailored` for today

If it reports 0 new jobs, say so and stop. Otherwise read every file in `.state/profile/` and `.state/run.json`.

## 2. Score every candidate

Read `.state/candidates.json` and score each job 0-100: how strong a candidate I am for it AND how well it matches my preferences. Be strict: a hard requirement I clearly lack, or any deal-breaker from my preferences (location, seniority, sponsorship, compensation, start date...), caps the score at 50.

Write `.state/results.json`: a JSON array with one object per job, in this shape:

```json
{
  "id": "<the job's id, exactly as in candidates.json>",
  "fit": 0,
  "recommendation": "apply | maybe | skip",
  "why_it_fits": "1-2 sentences citing concrete CV evidence",
  "gaps": "1-2 sentences: missing requirements, risks or preference conflicts; empty if none",
  "deal_breakers": ["preference deal-breakers this job hits"],
  "facts": {
    "workplace": "Remote | Hybrid | Onsite | Flexible | Unknown",
    "place": { "city": "", "state": "", "country": "", "lat": 0.0, "lng": 0.0 },
    "remote_region": "",
    "location_count": 0,
    "pay": { "min": 0, "max": 0, "currency": "USD", "period": "year | hour", "as_posted": "" }
  }
}
```

`facts` records what the posting states, for analysis. Read it from the posting's location, workplace, compensation and description; never infer or estimate:
- `workplace`: Remote (fully remote), Hybrid (some days in an office), Onsite, Flexible (remote or office, the candidate's choice), or Unknown if the posting doesn't say.
- `place`: the job's primary location, meaning the listed location that best matches my preferences, otherwise the first listed. Use the full, real place name (e.g. "New York", "New York", "United States") and the city center's coordinates to 4 decimals. Use `null` for remote-only jobs, and put where they hire in `remote_region` (e.g. "United States"); otherwise `remote_region` is "".
- `location_count`: how many distinct places are listed (0 for remote-only).
- `pay`: the stated base pay range. If ranges differ by location, use the range for `place`; if that isn't given, use the lowest minimum and highest maximum. `period` is "year" or "hour" as stated; `as_posted` quotes the text it came from. Use `null` if no range is stated: never estimate pay.

Score all of them before moving on; write the file as you go if there are many.

## 3. Prepare the best matches

The shortlist is jobs with `fit >= minFit` and a recommendation other than `skip`. Take the top `maxTailored` of them by fit. For each one:

**a. Find the hiring manager**: the person the role reports to (head of the team or function), not a recruiter. Use web search: the posting itself (it sometimes names the manager), the company's team or leadership pages, news, and searches such as `site:linkedin.com/in "<Company>" "<leader title for this function>"`. Use at most 6 searches per job. Only report a LinkedIn URL that appeared verbatim in a search result and has the form `https://www.linkedin.com/in/<handle>`; never construct one. Add to the job's object in results.json:

```json
"hiring_manager": { "name": "", "title": "", "linkedin_url": "", "confidence": "high | medium | low | none", "evidence": "one sentence on why this person" }
```

If you can't identify anyone with reasonable confidence, use confidence `none` with empty strings.

**b. Draft the materials** into `.state/materials/<company>-<short-title>.md` (lowercase, dashes), as plain text with exactly these headings, each on its own line, in this order:

```
<Company>: <Title>
<job URL>

NEEDS FROM YOU
• one bullet per piece of information this application needs that my files don't have, or "Nothing; ready to review."

HIRING MANAGER
<name, title (confidence: ...)>
<LinkedIn URL>
<evidence>
(or "Not identified.")

LINKEDIN NOTE (send yourself; the agent never contacts anyone)
<a connection note to the hiring manager, under 280 characters>

COVER LETTER
<250-350 words, addressed to the hiring team, specific to this role, only true claims>

CV TAILORING
• 3-6 concrete edits to my CV for this role (reorder, emphasize, reword); never invent

LIKELY QUESTIONS
Q: <a question this application is likely to ask: why this company, why this role, a relevant project...>
A: <my answer, from my files only>
```

Then add to the job's object in results.json: `"materials_file": ".state/materials/<file>.md"` and `"needs_from_you": [...]` (the same items as the NEEDS FROM YOU section; empty array if nothing).

## 4. Record

Run `npm run record`. It creates a Google Doc per materials file in `Applications/`, appends every scored job to the Application Tracker, and prints a summary. Finish by repeating that summary, plus anything that went wrong.
