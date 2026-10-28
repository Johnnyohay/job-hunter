# Job market database: Boston and the East Coast

Public sources only. No mock, estimated or filled-in rows. A source that fails leaves its table empty and logs the failure in `source_status`.

## Start (one time)

    bash ~/job-hunter/workers/market-db/setup.sh

This runs the first full pull and installs a refresh that runs once a day at 07:10.

## Files

| File | What it is |
|---|---|
| `jobmarket.db` | The database (SQLite, opens in DB Browser for SQLite, Python, R, Power BI) |
| `exports/*.csv` | Every table and view as CSV, rewritten after each update |
| `report.md` | "Where to aim": computed from the data after each update |
| `config.json` | Lanes, keywords, salary floor, areas, refresh intervals. Edit freely |
| `companies.json` | Job boards already confirmed (carried over from your deployment-radar project) |
| `companies_to_discover.txt` | Company names to look up. Add names, then run `discover` |
| `logs/` | Output of the first run and the daily runs |

## Commands

    python3 jobmarket.py status            what loaded, what failed, row counts
    python3 jobmarket.py update            pull whatever is due
    python3 jobmarket.py update --force    pull everything now
    python3 jobmarket.py update --only jobs
    python3 jobmarket.py discover          look up job boards for new company names
    python3 jobmarket.py export            rewrite exports/*.csv
    python3 jobmarket.py report            rewrite report.md

## Sources

| Table | Publisher | Content | Refresh check |
|---|---|---|---|
| `job_postings` | Employer career sites (Greenhouse, Lever, Ashby public APIs) | Live postings, tagged by lane, region, level, restriction wording, posted pay | daily |
| `posting_daily` | derived from `job_postings` | Daily count of open roles per company, lane, region (hiring trend over time) | daily |
| `lca` | US Department of Labor, OFLC | H-1B, H-1B1, E-3 filings with East Coast worksites: employer, title, wage | weekly |
| `oews` | BLS | Employment and wage percentiles by occupation, Boston and other East Coast metros | monthly |
| `laus` | BLS | Labor force, employment, unemployment by East Coast state and metro | weekly |
| `ces` | BLS | Jobs by industry, hours, earnings: MA, NH, RI, CT, NY areas | weekly |
| `jolts` | BLS | Openings, hires, quits, layoffs: national and East Coast states | weekly |
| `qcew` | BLS | Establishments, employment, wages by industry: Boston metro and counties, NYC, DC, Philadelphia | weekly |
| `qwi` | Census (LEHD) | Hires, separations, new-hire earnings by MA county and industry | monthly |
| `acs` | Census | Occupation, industry, earnings, education: Boston metro, MA, US | monthly |
| `cbp` | Census | Establishments, employment, payroll by county and industry | monthly |

## Known limits

- Not collected: LinkedIn, Indeed, Glassdoor (their terms forbid automated collection), career sites hosted on Workday or other systems, and company financial reports.
- `fit_tier`, `lane`, `region` and the restriction flags are keyword rules from `config.json` applied to the posting text. They are filters, not judgments.
- `wage_from_annualized` in `lca` is the filed wage when the unit is Year, or the hourly wage times 2080 when the unit is Hour. Other units are left empty.
- Optional: put a free Census API key in `config.json` (`census_api_key`) if Census calls are rate limited, and your email in `contact_email` if BLS downloads return 403 (BLS asks automated users to identify themselves).
