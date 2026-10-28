#!/usr/bin/env python3
"""
jobmarket.py - US East Coast / Boston job market database (public sources only).

Every row in the database comes from a live response of a public source.
Nothing is generated, estimated or filled in. If a source fails, the failure
is recorded in the `source_status` table and the table simply stays empty.

Commands:
  python3 jobmarket.py update            pull everything that is due
  python3 jobmarket.py update --force    pull everything, ignoring refresh intervals
  python3 jobmarket.py update --only jobs,laus
  python3 jobmarket.py discover          look for job boards of companies in companies_to_discover.txt
  python3 jobmarket.py export            write every table to exports/*.csv
  python3 jobmarket.py excel             write jobmarket.xlsx (one workbook, one sheet per topic)
  python3 jobmarket.py report            write report.md ("where to aim") from the data
  python3 jobmarket.py status            what loaded, what failed, row counts

Standard library only (Python 3.8+). Downloads use the system `curl`.
"""
import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import sqlite3
import statistics
import subprocess
import sys
import zipfile
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
from xml.etree.ElementTree import iterparse

HERE = os.path.dirname(os.path.abspath(__file__))
TODAY = dt.date.today().isoformat()
NOW = lambda: dt.datetime.now().isoformat(timespec="seconds")

# East Coast states: FIPS code -> postal abbreviation
EAST_COAST = {
    "23": "ME", "33": "NH", "50": "VT", "25": "MA", "44": "RI", "09": "CT",
    "36": "NY", "34": "NJ", "42": "PA", "10": "DE", "24": "MD", "11": "DC",
    "51": "VA", "37": "NC", "45": "SC", "13": "GA", "12": "FL",
}
EC_POSTAL = set(EAST_COAST.values())

DEFAULT_CONFIG = {
    "_readme": "Edit freely. Keys are read on every run.",
    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) jobmarket-db/1.0",
    "contact_email": "",
    "census_api_key": "",
    "min_year": 2015,
    "salary_floor": 150000,
    "refresh_days": {"jobs": 0, "laus": 7, "ces": 7, "jolts": 7, "oews": 30, "qcew": 7,
                     "acs": 30, "qwi": 30, "cbp": 30, "lca": 7, "discover": 30},
    "ces_files": ["sm.data.22.Massachusetts", "sm.data.30.NewHampshire", "sm.data.41.RhodeIsland",
                  "sm.data.7.Connecticut", "sm.data.33a.NewYork", "sm.data.33b.NewYork"],
    "oews_area_name_contains": ["Boston-Cambridge-Newton", "New York-Newark-Jersey City",
                                "Washington-Arlington-Alexandria", "Philadelphia-Camden-Wilmington",
                                "Worcester", "Providence-Warwick"],
    "qcew_areas": ["C1446", "25000", "25025", "25017", "25021", "25009", "25023",
                   "C3562", "C4790", "C3798", "US000"],
    "qcew_quarters_back": 10,
    "acs_groups": ["B24011", "C24010", "C24030", "B15003", "B23025"],
    "acs_geos": ["metropolitan%20statistical%20area/micropolitan%20statistical%20area:14460",
                 "state:25", "us:1"],
    "qwi_state": "25",
    "qwi_quarters_back": 8,
    "qwi_vars": ["Emp", "HirA", "HirN", "Sep", "EarnS", "EarnHirAS", "FrmJbGn", "FrmJbLs"],
    "qwi_sectors": ["00", "11", "21", "22", "23", "31-33", "42", "44-45", "48-49", "51", "52",
                    "53", "54", "55", "56", "61", "62", "71", "72", "81", "92"],
    "lca_discover_top_n": 200,
    "lca_min_fiscal_year": 2023,
    "workday_max_postings": 2000,
    "workday_max_detail_calls": 80,
    "report_soc_codes": ["13-1111", "13-1082", "13-1199", "13-1161", "15-2031", "15-2051",
                         "11-1021", "11-2021", "11-3021", "41-9031", "15-1299"],
    "lanes": {
        "deployment_strategy": ["deployment strategist", "forward deployed", "deployment lead",
                                "deployment manager", "ai strategist", "solution strategist",
                                "solutions strategist"],
        "strategy_analytics": ["strategy & analytics", "strategy and analytics", "strategy analyst",
                               "strategic analyst", "business analyst", "corporate strategy",
                               "strategic insights", "strategy associate", "strategy manager"],
        "bizops": ["bizops", "biz ops", "business operations", "strategy & operations",
                   "strategy and operations", "chief of staff"],
        "gtm_ops": ["gtm", "go-to-market", "go to market", "revenue operations", "revops",
                    "sales operations", "sales strategy", "marketing operations"],
        "solutions": ["solutions consultant", "solutions engineer", "solution engineer",
                      "sales engineer", "solutions architect", "technical account manager",
                      "pre-sales", "presales"],
        "ai_enablement": ["ai enablement", "ai success", "ai engagement", "ai solutions",
                          "ai transformation", "ai adoption", "ai program"],
        "delivery_impl": ["implementation", "technical delivery", "engagement manager",
                          "customer success", "technical program manager", "program manager",
                          "professional services"],
    },
    "adjacent_lanes": ["delivery_impl"],
    "level_too_senior": ["director", "vice president", " vp", "vp ", "vp,", "head of", "chief ",
                         "senior manager", "sr. manager", "sr manager"],
    "level_too_junior": ["intern", "internship", "new grad", "entry level", "entry-level",
                         "junior", "apprentice", "co-op"],
    "level_exceptions": ["chief of staff"],
    "title_exclude": ["recruiter", "recruiting", "software engineer", "engineering manager",
                      "account executive", "talent "],
    "restriction_patterns": {
        "us_person_or_clearance": [
            r"u\.?s\.?\s*person", r"united states person", r"security clearance",
            r"active clearance", r"\bts/sci\b", r"\b(secret|top secret) clearance\b",
            r"\bpolygraph\b", r"\b(active|current)\b[^.]{0,40}\bclearance\b", r"\bitar\b",
            r"u\.?s\.?\s*citizen(ship)?\s*(is\s*)?(required|only)", r"must be a u\.?s\.?\s*citizen",
        ],
        "no_sponsorship": [
            r"sponsorship[^.]{0,40}now or in the future",
            r"(not|unable to|cannot|can't|won't|will not)[^.]{0,30}sponsor",
            r"no (visa )?sponsorship", r"sponsorship is not available",
            r"without (the need for |requiring )?(visa |employer )?sponsorship",
        ],
    },
    "regions": {
        "boston_area": ["boston", "cambridge, ma", "cambridge, massachusetts", "somerville",
                        "waltham", "burlington, ma", "lexington, ma", "needham", "watertown, ma",
                        "massachusetts", ", ma"],
        "nyc": ["new york", "nyc", "brooklyn", "manhattan"],
        "east_coast_other": ["washington, dc", "washington, d.c", "philadelphia", "providence",
                             "hartford", "stamford", "jersey city", "newark", "baltimore",
                             "arlington, va", "reston", "mclean", "raleigh", "durham", "charlotte",
                             "atlanta", "miami", "tampa", "orlando", "portland, me", "portsmouth, nh",
                             "manchester, nh", "pittsburgh"],
        "non_us": ["london", "dublin", "toronto", "vancouver", "bangalore", "bengaluru", "berlin",
                   "paris", "singapore", "sydney", "tokyo", "amsterdam", "tel aviv", "warsaw",
                   "krakow", "india", "canada", "united kingdom", "emea", "apac", "germany",
                   "france", "israel", "mexico", "brazil", "poland", "ireland", "australia",
                   "japan", "netherlands", "spain", "sweden", "munich", "madrid", "stockholm"],
    },
}


def load_config():
    path = os.path.join(HERE, "config.json")
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(path):
        with open(path) as f:
            user = json.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict) and k in ("refresh_days",):
                cfg[k].update(v)
            else:
                cfg[k] = v
    else:
        with open(path, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
    return cfg


CFG = load_config()
CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)

# ---------------------------------------------------------------- HTTP (curl)
# Offline test hook: JOBMARKET_FIXTURES=<dir> with map.json {url: filename}.
# Used only by the test suite with a throwaway database. Never set in normal use.
_FIX = os.environ.get("JOBMARKET_FIXTURES")
_FIXMAP = json.load(open(os.path.join(_FIX, "map.json"))) if _FIX else None


class SourceError(Exception):
    pass


def _ua():
    ua = CFG["user_agent"]
    if CFG.get("contact_email"):
        ua += " (" + CFG["contact_email"] + ")"
    return ua


def http_get(url, timeout=120, data=None, headers=()):
    """Return (http_code, body_bytes, error_text). Never raises."""
    if _FIXMAP is not None:
        if url in _FIXMAP:
            with open(os.path.join(_FIX, _FIXMAP[url]), "rb") as f:
                return 200, f.read(), ""
        return 404, b"", "fixture: not mapped"
    cmd = ["curl", "-sSL", "--compressed", "--retry", "2", "--retry-delay", "3",
           "--max-time", str(timeout), "-A", _ua(), "-w", "\n%{http_code}"]
    for h in headers:
        cmd += ["-H", h]
    if data is not None:
        cmd += ["-H", "Content-Type: application/json", "--data", data]
    cmd.append(url)
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout + 60)
    except Exception as e:  # curl missing, timeout
        return 0, b"", str(e)
    out = p.stdout
    idx = out.rfind(b"\n")
    try:
        code = int(out[idx + 1:].strip() or 0)
    except ValueError:
        code = 0
    return code, out[:idx] if idx >= 0 else b"", p.stderr.decode("utf-8", "replace").strip()[:300]


def http_json(url, **kw):
    code, body, err = http_get(url, **kw)
    if code != 200:
        raise SourceError("HTTP %s %s %s" % (code, err, url))
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        raise SourceError("not JSON: %s" % url)


BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")


def http_download(url, dest, timeout=3600, referer=None):
    """Download to file. Returns http code."""
    if _FIXMAP is not None:
        if url in _FIXMAP:
            with open(os.path.join(_FIX, _FIXMAP[url]), "rb") as f, open(dest, "wb") as g:
                g.write(f.read())
            return 200
        return 404
    cmd = ["curl", "-sSL", "--compressed", "--retry", "2", "--max-time", str(timeout),
           "-A", BROWSER_UA if referer else _ua(), "-H", "Accept: */*", "-H", "Accept-Language: en-US,en;q=0.9"]
    if referer:
        cmd += ["-e", referer]
    cmd += ["-o", dest, "-w", "%{http_code}", url]
    p = subprocess.run(cmd, capture_output=True)
    try:
        return int(p.stdout.decode().strip() or 0)
    except ValueError:
        return 0


def http_lines(url, timeout=3600):
    """Stream a large text file line by line without keeping it. Raises SourceError."""
    if _FIXMAP is not None:
        if url not in _FIXMAP:
            raise SourceError("HTTP 404 (fixture) " + url)
        with open(os.path.join(_FIX, _FIXMAP[url]), encoding="utf-8", errors="replace") as f:
            for line in f:
                yield line
        return
    cmd = ["curl", "-sSL", "--fail", "--compressed", "--retry", "2", "--max-time", str(timeout),
           "-A", _ua(), url]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    n = 0
    for raw in p.stdout:
        n += 1
        yield raw.decode("utf-8", "replace")
    p.wait()
    if p.returncode != 0:
        raise SourceError("curl exit %s after %s lines: %s %s" % (
            p.returncode, n, p.stderr.read().decode("utf-8", "replace").strip()[:200], url))


def tsv_rows(url):
    """Small BLS lookup file: tab separated, first line is a header."""
    code, body, err = http_get(url)
    if code != 200:
        raise SourceError("HTTP %s %s %s" % (code, err, url))
    rows = []
    for i, line in enumerate(body.decode("utf-8", "replace").splitlines()):
        if i == 0 or not line.strip():
            continue
        rows.append([c.strip() for c in line.split("\t")])
    return rows


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- database
SCHEMA = """
CREATE TABLE IF NOT EXISTS source_status(
  source TEXT, run_at TEXT, status TEXT, rows INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS sources(
  source TEXT PRIMARY KEY, publisher TEXT, description TEXT, url TEXT);
CREATE TABLE IF NOT EXISTS laus(
  series_id TEXT, seasonal TEXT, area_code TEXT, area_name TEXT, state TEXT,
  measure_code TEXT, measure TEXT, year INTEGER, period TEXT, value REAL,
  PRIMARY KEY(series_id, year, period));
CREATE TABLE IF NOT EXISTS ces(
  series_id TEXT, seasonal TEXT, state_code TEXT, state TEXT, area_code TEXT, area_name TEXT,
  industry_code TEXT, industry_name TEXT, data_type_code TEXT, data_type TEXT,
  year INTEGER, period TEXT, value REAL, PRIMARY KEY(series_id, year, period));
CREATE TABLE IF NOT EXISTS jolts(
  series_id TEXT, seasonal TEXT, industry_code TEXT, industry TEXT, state_code TEXT, state TEXT,
  sizeclass_code TEXT, dataelement_code TEXT, dataelement TEXT, ratelevel_code TEXT, ratelevel TEXT,
  year INTEGER, period TEXT, value REAL, PRIMARY KEY(series_id, year, period));
CREATE TABLE IF NOT EXISTS oews(
  series_id TEXT, areatype_code TEXT, area_code TEXT, area_name TEXT, industry_code TEXT,
  occupation_code TEXT, occupation_name TEXT, datatype_code TEXT, datatype TEXT,
  year INTEGER, period TEXT, value REAL, value_text TEXT, footnotes TEXT,
  PRIMARY KEY(series_id, year, period));
CREATE TABLE IF NOT EXISTS acs(
  dataset TEXT, year INTEGER, geo TEXT, geo_name TEXT, table_id TEXT, variable TEXT,
  label TEXT, value REAL, value_text TEXT, PRIMARY KEY(dataset, year, geo, variable));
CREATE TABLE IF NOT EXISTS qwi(
  state TEXT, county TEXT, time TEXT, industry TEXT, variable TEXT, value REAL,
  PRIMARY KEY(state, county, time, industry, variable));
CREATE TABLE IF NOT EXISTS cbp(
  year INTEGER, state TEXT, county TEXT, name TEXT, naics TEXT, naics_label TEXT,
  establishments REAL, employment REAL, annual_payroll_k REAL,
  PRIMARY KEY(year, state, county, naics));
CREATE TABLE IF NOT EXISTS lca_files(filename TEXT PRIMARY KEY, url TEXT, loaded_at TEXT, rows INTEGER);
CREATE TABLE IF NOT EXISTS companies(
  name TEXT, provider TEXT, slug TEXT, origin TEXT, board_name TEXT, name_verified INTEGER,
  last_status TEXT, last_count INTEGER, last_checked TEXT, PRIMARY KEY(provider, slug));
CREATE TABLE IF NOT EXISTS discovery_log(
  name TEXT PRIMARY KEY, origin TEXT, checked_at TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS job_postings(
  id TEXT PRIMARY KEY, company TEXT, provider TEXT, slug TEXT, title TEXT, location TEXT,
  department TEXT, posted_at TEXT, url TEXT, comp_text TEXT, comp_min REAL, comp_max REAL,
  comp_source TEXT, lane TEXT, level_flag TEXT, region TEXT, restriction_flags TEXT,
  fit_tier TEXT, below_salary_floor INTEGER, first_seen TEXT, last_seen TEXT, is_open INTEGER,
  closed_on TEXT, description_text TEXT);
CREATE TABLE IF NOT EXISTS posting_daily(
  date TEXT, company TEXT, region TEXT, lane TEXT, fit_tier TEXT, open_count INTEGER,
  PRIMARY KEY(date, company, region, lane, fit_tier));
CREATE INDEX IF NOT EXISTS ix_jobs_open ON job_postings(is_open, fit_tier, region);
DROP VIEW IF EXISTS v_target_roles;
CREATE VIEW v_target_roles AS
  SELECT company, title, location, region, lane, fit_tier, comp_text, comp_min, comp_max,
         below_salary_floor, posted_at, first_seen, url
  FROM job_postings WHERE is_open=1 AND fit_tier IN ('target','adjacent')
  ORDER BY CASE region WHEN 'boston_area' THEN 0 WHEN 'nyc' THEN 1 WHEN 'east_coast_other' THEN 2
           WHEN 'remote' THEN 3 ELSE 4 END, fit_tier DESC, company;
DROP VIEW IF EXISTS v_company_hiring;
CREATE VIEW v_company_hiring AS
  SELECT company,
    SUM(is_open) AS open_roles_total,
    SUM(CASE WHEN is_open=1 AND region='boston_area' THEN 1 ELSE 0 END) AS open_boston,
    SUM(CASE WHEN is_open=1 AND fit_tier='target' THEN 1 ELSE 0 END) AS open_target_lane,
    SUM(CASE WHEN is_open=1 AND fit_tier='target' AND region='boston_area' THEN 1 ELSE 0 END) AS open_target_boston,
    SUM(CASE WHEN first_seen >= date('now','-30 day') THEN 1 ELSE 0 END) AS first_seen_last_30d,
    SUM(CASE WHEN closed_on >= date('now','-30 day') THEN 1 ELSE 0 END) AS closed_last_30d
  FROM job_postings GROUP BY company;
"""

SOURCES = [
    ("laus", "BLS", "Local Area Unemployment Statistics: labor force, employment, unemployment by state and metro", "https://download.bls.gov/pub/time.series/la/"),
    ("ces", "BLS", "Current Employment Statistics, State and Area: jobs by industry, hours, earnings", "https://download.bls.gov/pub/time.series/sm/"),
    ("jolts", "BLS", "Job Openings and Labor Turnover Survey: openings, hires, quits, layoffs (national and state)", "https://download.bls.gov/pub/time.series/jt/"),
    ("oews", "BLS", "Occupational Employment and Wage Statistics: employment and wage percentiles by occupation and metro", "https://download.bls.gov/pub/time.series/oe/"),
    ("qcew", "BLS", "Quarterly Census of Employment and Wages: establishments, employment, wages by industry and area", "https://data.bls.gov/cew/data/api/"),
    ("acs", "US Census Bureau", "American Community Survey 1-year: occupation, industry, earnings, education", "https://api.census.gov/data/"),
    ("qwi", "US Census Bureau (LEHD)", "Quarterly Workforce Indicators: hires, separations, earnings of new hires by county and industry", "https://api.census.gov/data/timeseries/qwi/sa"),
    ("cbp", "US Census Bureau", "County Business Patterns: establishments, employment, payroll by county and industry", "https://api.census.gov/data/"),
    ("lca", "US Department of Labor (OFLC)", "H-1B / H-1B1 / E-3 Labor Condition Application disclosure data: employer, job title, worksite, offered wage", "https://www.dol.gov/agencies/eta/foreign-labor/performance"),
    ("jobs", "Employer career sites", "Live postings from public Greenhouse, Lever and Ashby job-board APIs", "https://boards-api.greenhouse.io / https://api.lever.co / https://api.ashbyhq.com"),
]


def open_db(path):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.executemany("INSERT OR REPLACE INTO sources VALUES(?,?,?,?)", SOURCES)
    db.commit()
    return db


def record(db, source, status, rows, detail):
    db.execute("INSERT INTO source_status VALUES(?,?,?,?,?)", (source, NOW(), status, rows, detail[:1000]))
    db.commit()
    print("  [%s] %s: %s rows. %s" % (status.upper(), source, rows, detail[:200]))


def is_due(db, source, force):
    if force:
        return True
    days = CFG["refresh_days"].get(source, 7)
    r = db.execute("SELECT max(run_at) FROM source_status WHERE source=? AND status='ok'", (source,)).fetchone()[0]
    if not r:
        return True
    return (dt.datetime.now() - dt.datetime.fromisoformat(r)).total_seconds() >= days * 86400 - 3600


# ---------------------------------------------------------------- BLS sources
def src_laus(db):
    base = "https://download.bls.gov/pub/time.series/la/"
    areas = {r[1]: r[2] for r in tsv_rows(base + "la.area") if len(r) >= 3}
    measures = {r[0]: r[1] for r in tsv_rows(base + "la.measure") if len(r) >= 2}
    n = 0
    for fname in ("la.data.60.Metro", "la.data.3.AllStatesS", "la.data.2.AllStatesU"):
        batch = []
        for i, line in enumerate(http_lines(base + fname)):
            if i == 0:
                continue
            p = line.split("\t")
            if len(p) < 4:
                continue
            sid = p[0].strip()
            area = sid[3:18]
            st = area[2:4]
            if st not in EAST_COAST:
                continue
            year = int(p[1])
            if year < CFG["min_year"]:
                continue
            m = sid[18:20]
            batch.append((sid, sid[2], area, areas.get(area), EAST_COAST[st], m, measures.get(m),
                          year, p[2].strip(), num(p[3].strip())))
        db.executemany("INSERT OR REPLACE INTO laus VALUES(?,?,?,?,?,?,?,?,?,?)", batch)
        n += len(batch)
    return n, "metro and state series, East Coast, %s onward" % CFG["min_year"]


def src_ces(db):
    base = "https://download.bls.gov/pub/time.series/sm/"
    areas = {r[0]: r[1] for r in tsv_rows(base + "sm.area") if len(r) >= 2}
    inds = {r[0]: r[1] for r in tsv_rows(base + "sm.industry") if len(r) >= 2}
    dts = {r[0]: r[1] for r in tsv_rows(base + "sm.data_type") if len(r) >= 2}
    states = {r[0]: r[1] for r in tsv_rows(base + "sm.state") if len(r) >= 2}
    n, missing = 0, []
    for fname in CFG["ces_files"]:
        batch = []
        try:
            for i, line in enumerate(http_lines(base + fname)):
                if i == 0:
                    continue
                p = line.split("\t")
                if len(p) < 4:
                    continue
                year = int(p[1])
                if year < CFG["min_year"]:
                    continue
                sid = p[0].strip()
                st, ar, ind, d = sid[3:5], sid[5:10], sid[10:18], sid[18:20]
                batch.append((sid, sid[2], st, states.get(st), ar, areas.get(ar), ind, inds.get(ind),
                              d, dts.get(d), year, p[2].strip(), num(p[3].strip())))
        except SourceError as e:
            missing.append("%s (%s)" % (fname, str(e)[:60]))
            continue
        db.executemany("INSERT OR REPLACE INTO ces VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        n += len(batch)
    if n == 0:
        raise SourceError("no CES file loaded: " + "; ".join(missing))
    return n, "files: %s%s" % (len(CFG["ces_files"]) - len(missing),
                               ("; FAILED: " + "; ".join(missing)) if missing else "")


def src_jolts(db):
    base = "https://download.bls.gov/pub/time.series/jt/"
    inds = {r[0]: r[1] for r in tsv_rows(base + "jt.industry") if len(r) >= 2}
    states = {r[0]: r[1] for r in tsv_rows(base + "jt.state") if len(r) >= 2}
    els = {r[0]: r[1] for r in tsv_rows(base + "jt.dataelement") if len(r) >= 2}
    rls = {r[0]: r[1] for r in tsv_rows(base + "jt.ratelevel") if len(r) >= 2}
    batch = []
    for i, line in enumerate(http_lines(base + "jt.data.1.AllItems")):
        if i == 0:
            continue
        p = line.split("\t")
        if len(p) < 4:
            continue
        sid = p[0].strip()
        st = sid[9:11]
        if st != "00" and st not in EAST_COAST:
            continue
        year = int(p[1])
        if year < CFG["min_year"]:
            continue
        ind, el, rl = sid[3:9], sid[18:20], sid[20:21]
        batch.append((sid, sid[2], ind, inds.get(ind), st, states.get(st), sid[16:18], el, els.get(el),
                      rl, rls.get(rl), year, p[2].strip(), num(p[3].strip())))
    db.executemany("INSERT OR REPLACE INTO jolts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
    return len(batch), "national plus East Coast states"


def src_oews(db):
    base = "https://download.bls.gov/pub/time.series/oe/"
    occ = {r[0]: r[1] for r in tsv_rows(base + "oe.occupation") if len(r) >= 2}
    dtp = {r[0]: r[1] for r in tsv_rows(base + "oe.datatype") if len(r) >= 2}
    prefixes = {}
    for r in tsv_rows(base + "oe.area"):
        if len(r) < 4:
            continue
        st, area, atype, name = r[0], r[1], r[2], r[3]
        keep = (atype == "N") or (atype == "S" and st in EAST_COAST) or \
               any(s.lower() in name.lower() for s in CFG["oews_area_name_contains"])
        if keep:
            prefixes["OEU" + atype + area + "000000"] = name
    if not prefixes:
        raise SourceError("no matching areas in oe.area")
    plen = len(next(iter(prefixes)))
    batch, n = [], 0
    for i, line in enumerate(http_lines(base + "oe.data.0.Current")):
        if i == 0 or line[:plen] not in prefixes:
            continue
        p = line.split("\t")
        if len(p) < 4:
            continue
        sid = p[0].strip()
        vt = p[3].strip()
        o, d = sid[17:23], sid[23:25]
        batch.append((sid, sid[3], sid[4:11], prefixes[sid[:plen]], sid[11:17], o, occ.get(o), d,
                      dtp.get(d), int(p[1]), p[2].strip(), num(vt), vt,
                      p[4].strip() if len(p) > 4 else ""))
        if len(batch) >= 50000:
            db.executemany("INSERT OR REPLACE INTO oews VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
            n += len(batch)
            batch = []
    db.executemany("INSERT OR REPLACE INTO oews VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
    n += len(batch)
    if n == 0:
        raise SourceError("file read but no rows matched %s area prefixes" % len(prefixes))
    return n, "%s areas, all occupations, cross-industry" % len(prefixes)


def src_qcew(db):
    have = set()
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='qcew'").fetchone():
        have = {r[0] for r in db.execute("SELECT DISTINCT area_fips||'|'||year||'|'||qtr FROM qcew")}
    today = dt.date.today()
    y, q = today.year, (today.month - 1) // 3 + 1
    quarters = []
    for _ in range(CFG["qcew_quarters_back"]):
        q -= 1
        if q == 0:
            y, q = y - 1, 4
        quarters.append((y, q))
    n, got, notyet = 0, 0, 0
    for (yy, qq) in quarters:
        for area in CFG["qcew_areas"]:
            if "%s|%s|%s" % (area, yy, qq) in have:
                continue
            url = "https://data.bls.gov/cew/data/api/%s/%s/area/%s.csv" % (yy, qq, area)
            code, body, err = http_get(url)
            if code != 200:
                notyet += 1
                continue
            rdr = csv.reader(body.decode("utf-8", "replace").splitlines())
            header = next(rdr, None)
            if not header or "area_fips" not in header:
                continue
            cols = [re.sub(r"\W", "_", h) for h in header]
            db.execute("CREATE TABLE IF NOT EXISTS qcew(%s, PRIMARY KEY(area_fips, own_code, industry_code, agglvl_code, size_code, year, qtr))"
                       % ", ".join('"%s"' % c for c in cols))
            existing = [r[1] for r in db.execute("PRAGMA table_info(qcew)")]
            rows = []
            for r in rdr:
                if len(r) != len(cols):
                    continue
                d = dict(zip(cols, r))
                rows.append([d.get(c) for c in existing])
            db.executemany("INSERT OR REPLACE INTO qcew VALUES(%s)" % ",".join("?" * len(existing)), rows)
            n += len(rows)
            got += 1
    for kind in ("area", "industry"):
        code, body, err = http_get("https://data.bls.gov/cew/doc/titles/%s/%s_titles.csv" % (kind, kind))
        if code == 200:
            rdr = csv.reader(body.decode("utf-8", "replace").splitlines())
            next(rdr, None)
            db.execute("CREATE TABLE IF NOT EXISTS qcew_%s_titles(code TEXT PRIMARY KEY, title TEXT)" % kind)
            db.executemany("INSERT OR REPLACE INTO qcew_%s_titles VALUES(?,?)" % kind,
                           [r[:2] for r in rdr if len(r) >= 2])
    if got == 0 and not have:
        raise SourceError("no area-quarter file could be downloaded (%s attempts)" % notyet)
    return n, "%s new area-quarter files; %s not available (not yet published or not found)" % (got, notyet)


# ---------------------------------------------------------------- Census sources
def _ckey():
    if not CFG.get("census_api_key"):
        raise SourceError("the Census API requires a free key on every request. Get one at "
                          "https://api.census.gov/data/key_signup.html and put it in config.json as census_api_key")
    return "&key=" + CFG["census_api_key"]


def src_acs(db):
    _ckey()
    n, years_ok, errs = 0, [], []
    for year in range(dt.date.today().year - 1, dt.date.today().year - 5, -1):
        if len(years_ok) >= 2:
            break
        base = "https://api.census.gov/data/%s/acs/acs1" % year
        year_rows = 0
        for g in CFG["acs_groups"]:
            try:
                meta = http_json("%s/groups/%s.json" % (base, g))
                labels = {k: v.get("label", "") for k, v in meta.get("variables", {}).items()}
            except SourceError as e:
                errs.append("%s %s: %s" % (year, g, str(e)[:50]))
                break
            for geo in CFG["acs_geos"]:
                try:
                    data = http_json("%s?get=group(%s)&for=%s%s" % (base, g, geo, _ckey()))
                except SourceError as e:
                    errs.append("%s %s %s: %s" % (year, g, geo[-12:], str(e)[:50]))
                    continue
                if not data or len(data) < 2:
                    continue
                hdr, vals = data[0], data[1]
                d = dict(zip(hdr, vals))
                rows = []
                for var, val in d.items():
                    if not re.match(r"^%s_\d+[EM]$" % g, var):
                        continue
                    rows.append(("acs1", year, geo.replace("%20", " "), d.get("NAME"), g, var,
                                 labels.get(var, ""), num(val), val))
                db.executemany("INSERT OR REPLACE INTO acs VALUES(?,?,?,?,?,?,?,?,?)", rows)
                year_rows += len(rows)
        if year_rows:
            years_ok.append(year)
            n += year_rows
    if n == 0:
        raise SourceError("no ACS data returned: " + "; ".join(errs[:4]))
    return n, "years loaded: %s%s" % (years_ok, ("; some calls failed: " + "; ".join(errs[:3])) if errs else "")


def src_qwi(db):
    _ckey()
    st = CFG["qwi_state"]
    today = dt.date.today()
    y, q = today.year, (today.month - 1) // 3 + 1
    quarters = []
    for _ in range(CFG["qwi_quarters_back"] + 3):
        q -= 1
        if q == 0:
            y, q = y - 1, 4
        quarters.append("%s-Q%s" % (y, q))
    vars_ = CFG["qwi_vars"]
    base = "https://api.census.gov/data/timeseries/qwi/sa?get=%s%%s&for=county:*&in=state:%s&time=%%s&ownercode=A05&seasonadj=U&sex=0&agegrp=A00%s" % (
        ",".join(vars_), st, _ckey())
    n, loaded, errs = 0, 0, []

    def store(data):
        hdr = data[0]
        rows = []
        for r in data[1:]:
            d = dict(zip(hdr, r))
            for v in vars_:
                if d.get(v) is not None:
                    rows.append((d.get("state"), d.get("county"), d.get("time"), d.get("industry"), v, num(d.get(v))))
        db.executemany("INSERT OR REPLACE INTO qwi VALUES(?,?,?,?,?,?)", rows)
        return len(rows)

    mode = None  # 'all' = industry returned as a column in one call, 'loop' = one call per sector
    for t in quarters:
        if loaded >= CFG["qwi_quarters_back"]:
            break
        if db.execute("SELECT 1 FROM qwi WHERE state=? AND time=? LIMIT 1", (st, t)).fetchone():
            loaded += 1
            continue
        got = 0
        if mode in (None, "all"):
            code, body, err = http_get(base % (",industry", t))
            if code == 200 and body.strip():
                try:
                    data = json.loads(body)
                    if len({r[data[0].index("industry")] for r in data[1:]}) > 1:
                        mode = "all"
                        got = store(data)
                    elif mode is None:
                        mode = "loop"
                except (ValueError, IndexError):
                    mode = mode or "loop"
            elif code == 204 or (code == 200 and not body.strip()):
                continue  # quarter not published yet
            else:
                if mode is None:
                    mode = "loop"
        if mode == "loop":
            for sec in CFG["qwi_sectors"]:
                code, body, err = http_get((base % ("", t)) + "&industry=" + sec)
                if code == 200 and body.strip():
                    try:
                        got += store(json.loads(body))
                    except ValueError:
                        pass
                elif code not in (204, 200):
                    errs.append("%s %s HTTP %s" % (t, sec, code))
                    if len(errs) > 6:
                        break
        if got:
            loaded += 1
            n += got
        if len(errs) > 6:
            break
    if n == 0 and loaded == 0:
        raise SourceError("no QWI data returned: " + "; ".join(errs[:4]))
    return n, "quarters present: %s, mode=%s%s" % (loaded, mode, ("; errors: " + "; ".join(errs[:3])) if errs else "")


def src_cbp(db):
    _ckey()
    errs = []
    for year in range(dt.date.today().year - 1, dt.date.today().year - 6, -1):
        n = 0
        for st in ("25", "36", "33", "44", "09"):
            url = "https://api.census.gov/data/%s/cbp?get=NAME,NAICS2017,NAICS2017_LABEL,ESTAB,EMP,PAYANN&for=county:*&in=state:%s%s" % (year, st, _ckey())
            try:
                data = http_json(url)
            except SourceError as e:
                errs.append("%s/%s: %s" % (year, st, str(e)[:40]))
                continue
            hdr = data[0]
            rows = []
            for r in data[1:]:
                d = dict(zip(hdr, r))
                rows.append((year, d.get("state"), d.get("county"), d.get("NAME"), d.get("NAICS2017"),
                             d.get("NAICS2017_LABEL"), num(d.get("ESTAB")), num(d.get("EMP")), num(d.get("PAYANN"))))
            db.executemany("INSERT OR REPLACE INTO cbp VALUES(?,?,?,?,?,?,?,?,?)", rows)
            n += len(rows)
        if n:
            return n, "reference year %s, counties in MA NY NH RI CT" % year
    raise SourceError("no CBP year returned data: " + "; ".join(errs[:4]))


# ---------------------------------------------------------------- DOL LCA (H-1B) disclosure
def xlsx_rows(path):
    """Stream rows of the first worksheet of an .xlsx as {col_index: value}. Stdlib only."""
    z = zipfile.ZipFile(path)
    names = z.namelist()
    ss = []
    if "xl/sharedStrings.xml" in names:
        with z.open("xl/sharedStrings.xml") as f:
            for _, el in iterparse(f):
                if el.tag.endswith("}si"):
                    ss.append("".join(t.text or "" for t in el.iter() if t.tag.endswith("}t")))
                    el.clear()
    sheets = sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    if not sheets:
        raise SourceError("xlsx has no worksheet")
    with z.open(sheets[0]) as f:
        for _, el in iterparse(f):
            if not el.tag.endswith("}row"):
                continue
            row = {}
            for c in el:
                ref = c.get("r") or ""
                letters = re.match(r"[A-Z]+", ref)
                if not letters:
                    continue
                idx = 0
                for ch in letters.group(0):
                    idx = idx * 26 + (ord(ch) - 64)
                t = c.get("t")
                val = None
                if t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter() if x.tag.endswith("}t"))
                else:
                    v = None
                    for x in c:
                        if x.tag.endswith("}v"):
                            v = x.text
                    if v is not None:
                        val = ss[int(v)] if t == "s" else v
                row[idx - 1] = val
            yield row
            el.clear()


LCA_WANTED = ["CASE_NUMBER", "CASE_STATUS", "RECEIVED_DATE", "DECISION_DATE", "VISA_CLASS", "JOB_TITLE",
              "SOC_CODE", "SOC_TITLE", "FULL_TIME_POSITION", "BEGIN_DATE", "END_DATE",
              "TOTAL_WORKER_POSITIONS", "NEW_EMPLOYMENT", "EMPLOYER_NAME", "TRADE_NAME_DBA",
              "EMPLOYER_CITY", "EMPLOYER_STATE", "NAICS_CODE", "WORKSITE_CITY", "WORKSITE_COUNTY",
              "WORKSITE_STATE", "WORKSITE_POSTAL_CODE", "WAGE_RATE_OF_PAY_FROM", "WAGE_RATE_OF_PAY_TO",
              "WAGE_UNIT_OF_PAY", "PREVAILING_WAGE", "PW_UNIT_OF_PAY", "PW_WAGE_LEVEL",
              "H_1B_DEPENDENT", "WILLFUL_VIOLATOR"]


def _xl_date(v):
    try:
        f = float(v)
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(f))).isoformat()
    except (TypeError, ValueError):
        return v


def _annual(v, unit):
    """Annual wage only when the filing states a yearly or hourly unit (hourly x 2080)."""
    x = num(str(v).replace(",", "").replace("$", "")) if v is not None else None
    if x is None or not unit:
        return None
    u = unit.strip().lower()
    if u.startswith("year"):
        return x
    if u.startswith("hour"):
        return round(x * 2080, 2)
    return None


def src_lca(db):
    page = "https://www.dol.gov/agencies/eta/foreign-labor/performance"
    code, body, err = http_get(page)
    if code != 200:
        raise SourceError("HTTP %s %s on the OFLC performance page" % (code, err))
    text = body.decode("utf-8", "replace")
    found = {}
    for m in re.finditer(r'href="([^"]*?(LCA_Disclosure_Data_FY(\d{4})_Q(\d)\.xlsx))"', text, re.I):
        href, fname, fy, q = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        if href.startswith("/"):
            href = "https://www.dol.gov" + href
        found[(fy, q)] = (fname, href)
    if not found:
        raise SourceError("no LCA_Disclosure_Data_FYxxxx_Qx.xlsx link found on the OFLC page (layout may have changed)")
    picks = sorted(k for k in found if k[0] >= CFG.get("lca_min_fiscal_year", 2023))
    if not picks:
        picks = [max(found)]
    total, notes = 0, []
    for key in picks:
        fname, href = found[key]
        if db.execute("SELECT 1 FROM lca_files WHERE filename=?", (fname,)).fetchone():
            notes.append(fname + " already loaded")
            continue
        dest = os.path.join(CACHE, fname)
        code = http_download(href, dest, referer=page)
        if code != 200:
            notes.append("%s HTTP %s" % (fname, code))
            continue
        header, cols, n, batch = None, None, 0, []
        for row in xlsx_rows(dest):
            if header is None:
                header = {i: (v or "").strip().upper() for i, v in row.items()}
                inv = {v: i for i, v in header.items()}
                cols = [c for c in LCA_WANTED if c in inv]
                if "CASE_NUMBER" not in inv:
                    raise SourceError("%s: CASE_NUMBER column not found" % fname)
                state_col = "WORKSITE_STATE" if "WORKSITE_STATE" in inv else "EMPLOYER_STATE"
                db.execute("CREATE TABLE IF NOT EXISTS lca(source_file TEXT, fiscal_year INTEGER, %s, "
                           "wage_from_annualized REAL, PRIMARY KEY(CASE_NUMBER, source_file))"
                           % ", ".join('"%s" TEXT' % c for c in LCA_WANTED))
                continue
            st = (row.get(inv.get(state_col, -1)) or "").strip().upper()
            if st not in EC_POSTAL:
                continue
            d = {c: row.get(inv[c]) for c in cols}
            for c in cols:
                if c.endswith("_DATE") and d[c] is not None:
                    d[c] = _xl_date(d[c])
            batch.append([fname, key[0]] + [d.get(c) for c in LCA_WANTED] +
                         [_annual(d.get("WAGE_RATE_OF_PAY_FROM"), d.get("WAGE_UNIT_OF_PAY"))])
            if len(batch) >= 20000:
                db.executemany("INSERT OR REPLACE INTO lca VALUES(%s)" % ",".join("?" * (len(LCA_WANTED) + 3)), batch)
                n += len(batch)
                batch = []
        if header is not None:
            db.executemany("INSERT OR REPLACE INTO lca VALUES(%s)" % ",".join("?" * (len(LCA_WANTED) + 3)), batch)
            n += len(batch)
        # some quarterly files are cumulative for the fiscal year: keep each case once, from the newest file
        db.execute("DELETE FROM lca WHERE source_file<>? AND CASE_NUMBER IN "
                   "(SELECT CASE_NUMBER FROM lca WHERE source_file=?)", (fname, fname))
        db.execute("INSERT OR REPLACE INTO lca_files VALUES(?,?,?,?)", (fname, href, NOW(), n))
        db.commit()
        try:
            os.remove(dest)
        except OSError:
            pass
        total += n
        notes.append("%s: %s East Coast rows" % (fname, n))
    if total == 0 and not db.execute("SELECT 1 FROM lca_files").fetchone():
        raise SourceError("; ".join(notes))
    return total, "; ".join(notes)


# ---------------------------------------------------------------- live job postings
TAG = re.compile(r"<[^>]+>")


def strip_html(s):
    if not s:
        return ""
    s = html.unescape(s)
    s = TAG.sub(" ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def fetch_greenhouse(slug):
    j = http_json("https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=true&pay_transparency=true" % quote(slug), timeout=90)
    out = []
    for x in j.get("jobs", []):
        pr = x.get("pay_input_ranges") or []
        cmin = cmax = None
        ctext = ""
        if pr:
            mins = [p["min_cents"] / 100.0 for p in pr if p.get("min_cents")]
            maxs = [p["max_cents"] / 100.0 for p in pr if p.get("max_cents")]
            cmin = min(mins) if mins else None
            cmax = max(maxs) if maxs else None
            ctext = "; ".join("%s %s-%s %s" % (p.get("title") or "", (p.get("min_cents") or 0) / 100,
                                                (p.get("max_cents") or 0) / 100, p.get("currency_type") or "") for p in pr)
        out.append(dict(jid=str(x.get("id")), title=x.get("title") or "", location=(x.get("location") or {}).get("name") or "",
                        department=((x.get("departments") or [{}])[0] or {}).get("name") or "",
                        posted_at=x.get("first_published") or x.get("updated_at") or "", url=x.get("absolute_url") or "",
                        desc=strip_html(x.get("content")), comp_text=ctext, comp_min=cmin, comp_max=cmax,
                        comp_source="structured" if pr else None))
    return out


def fetch_lever(slug):
    j = http_json("https://api.lever.co/v0/postings/%s?mode=json" % quote(slug), timeout=90)
    if not isinstance(j, list):
        raise SourceError("unexpected Lever response")
    out = []
    for x in j:
        cat = x.get("categories") or {}
        lists = " ".join("%s %s" % (l.get("text") or "", l.get("content") or "") for l in (x.get("lists") or []))
        sr = x.get("salaryRange") or {}
        ts = x.get("createdAt")
        out.append(dict(jid=str(x.get("id")), title=x.get("text") or "", location=cat.get("location") or "",
                        department=cat.get("team") or cat.get("department") or "",
                        posted_at=(dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=ts)).isoformat(timespec="seconds") if ts else "",
                        url=x.get("hostedUrl") or "",
                        desc=strip_html("%s %s %s" % (x.get("descriptionPlain") or x.get("description") or "", lists, x.get("additionalPlain") or "")),
                        comp_text=("%s-%s %s per %s" % (sr.get("min"), sr.get("max"), sr.get("currency"), sr.get("interval"))) if sr else "",
                        comp_min=num(sr.get("min")) if sr and "year" in str(sr.get("interval", "")).lower() else None,
                        comp_max=num(sr.get("max")) if sr and "year" in str(sr.get("interval", "")).lower() else None,
                        comp_source="structured" if sr else None))
    return out


def fetch_ashby(slug):
    j = http_json("https://api.ashbyhq.com/posting-api/job-board/%s?includeCompensation=true" % quote(slug), timeout=90)
    out = []
    for x in j.get("jobs", []):
        if x.get("isListed") is False:
            continue
        comp = x.get("compensation") or {}
        ctext = comp.get("compensationTierSummary") or x.get("compensationTierSummary") or ""
        out.append(dict(jid=str(x.get("id")), title=x.get("title") or "", location=x.get("location") or "",
                        department=x.get("department") or x.get("team") or "",
                        posted_at=x.get("publishedAt") or x.get("publishedDate") or "",
                        url=x.get("jobUrl") or x.get("applyUrl") or "",
                        desc=strip_html(x.get("descriptionHtml")) or (x.get("descriptionPlain") or ""),
                        comp_text=ctext, comp_min=None, comp_max=None, comp_source="structured" if ctext else None))
    return out


def fetch_workday(slug):
    """slug = '<tenant>.<pod>/<site>', e.g. 'fmr.wd1/FidelityCareers' (from the employer's own careers URL).
    Uses the JSON the employer's public Workday careers page itself loads. Listing pages hold title and
    location only, so the full description is fetched just for titles that match a lane."""
    hostpart, site = slug.split("/", 1)
    tenant = hostpart.split(".")[0]
    host = "https://%s.myworkdayjobs.com" % hostpart
    api = "%s/wday/cxs/%s/%s" % (host, tenant, site)
    hdr = ("Accept: application/json", "Accept-Language: en-US")
    out, offset, total, details = [], 0, None, 0
    lane_words = [k for ks in CFG["lanes"].values() for k in ks]
    while offset < CFG.get("workday_max_postings", 2000):
        j = http_json(api + "/jobs", timeout=60, headers=hdr,
                      data=json.dumps({"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""}))
        posts = j.get("jobPostings") or []
        if total is None:
            total = j.get("total") or 0
        for x in posts:
            path = x.get("externalPath") or ""
            title = x.get("title") or ""
            job = dict(jid=path.rsplit("/", 1)[-1] or title, title=title, location=x.get("locationsText") or "",
                       department="", posted_at=x.get("postedOn") or "", url="%s/en-US/%s%s" % (host, site, path),
                       desc="", comp_text="", comp_min=None, comp_max=None, comp_source=None)
            t = " " + title.lower() + " "
            if path and details < CFG.get("workday_max_detail_calls", 80) and any(k in t for k in lane_words):
                details += 1
                try:
                    d = http_json(api + path, timeout=60, headers=hdr)
                    info = d.get("jobPostingInfo") or d
                    job["desc"] = strip_html(info.get("jobDescription"))
                    locs = [info.get("location")] + list(info.get("additionalLocations") or [])
                    locs = [l for l in locs if l]
                    if locs:
                        job["location"] = "; ".join(locs)
                    if info.get("startDate"):
                        job["posted_at"] = info["startDate"]
                except SourceError:
                    pass
            out.append(job)
        if len(posts) < 20:
            break
        offset += 20
    return out


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby, "workday": fetch_workday}

MONEY_RANGE = re.compile(r"\$\s?(\d{2,3}(?:,\d{3})|\d{2,3}\s?[kK])\s*(?:-|–|—|to)\s*\$?\s?(\d{2,3}(?:,\d{3})|\d{2,3}\s?[kK])")


def _money(s):
    s = s.replace(",", "").strip()
    if s[-1] in "kK":
        return float(s[:-1].strip()) * 1000
    return float(s)


def classify(job):
    title = " " + job["title"].lower() + " "
    text = (job["title"] + " " + job["desc"]).lower()
    loc = job["location"].lower()
    lane = ""
    for name, kws in ({} if any(k in title for k in CFG.get("title_exclude", [])) else CFG["lanes"]).items():
        if any(k in title for k in kws):
            lane = name
            break
    level = ""
    if not any(e in title for e in CFG["level_exceptions"]):
        if any(k in title for k in CFG["level_too_senior"]):
            level = "too_senior"
        elif any(re.search(r"\b%s\b" % re.escape(k), title) for k in CFG["level_too_junior"]):
            level = "too_junior"
    flags = []
    for fname, pats in CFG["restriction_patterns"].items():
        if any(re.search(p, text, re.I) for p in pats):
            flags.append(fname)
    region = "us_other_or_unspecified"
    rg = CFG["regions"]
    if any(k in loc for k in rg["boston_area"]):
        region = "boston_area"
    elif any(k in loc for k in rg["nyc"]):
        region = "nyc"
    elif any(k in loc for k in rg["east_coast_other"]):
        region = "east_coast_other"
    elif any(k in loc for k in rg["non_us"]):
        region = "non_us"
    elif "remote" in loc:
        region = "remote"
    cmin, cmax, csrc, ctext = job["comp_min"], job["comp_max"], job["comp_source"], job["comp_text"]
    if cmin is None and cmax is None:
        m = MONEY_RANGE.search(ctext or "") or MONEY_RANGE.search(job["desc"])
        if m:
            try:
                a, b = _money(m.group(1)), _money(m.group(2))
                if 20000 <= a <= b <= 2000000:
                    cmin, cmax = a, b
                    csrc = "text_pattern"
                    ctext = ctext or m.group(0)
            except ValueError:
                pass
    if not lane:
        tier = "other"
    elif flags or level or region == "non_us":
        tier = "excluded"
    elif lane in CFG["adjacent_lanes"]:
        tier = "adjacent"
    else:
        tier = "target"
    below = None
    if cmax is not None:
        below = 1 if cmax < CFG["salary_floor"] else 0
    return lane, level, region, ",".join(flags), tier, cmin, cmax, csrc, ctext, below


def seed_workday_sites(db):
    path = os.path.join(HERE, "workday_sites.txt")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            if "|" not in line or line.strip().startswith("#"):
                continue
            name, url = [x.strip() for x in line.split("|", 1)]
            m = re.match(r"https://([a-z0-9_-]+\.wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#\s]+)", url)
            if name and m:
                db.execute("INSERT OR IGNORE INTO companies(name, provider, slug, origin, name_verified) VALUES(?,?,?,?,1)",
                           (name, "workday", "%s/%s" % (m.group(1), m.group(2)), "workday_sites.txt"))
    db.commit()


def seed_companies(db):
    seed_workday_sites(db)
    path = os.path.join(HERE, "companies.json")
    if not os.path.exists(path):
        return
    with open(path) as f:
        items = json.load(f)
    for c in items:
        if c.get("provider") in FETCHERS and c.get("slug"):
            db.execute("INSERT OR IGNORE INTO companies(name, provider, slug, origin, name_verified) VALUES(?,?,?,?,1)",
                       (c["name"], c["provider"], c["slug"], c.get("origin", "companies.json")))
    db.commit()


def src_jobs(db):
    seed_companies(db)
    boards = db.execute("SELECT name, provider, slug FROM companies WHERE name_verified=1").fetchall()
    if not boards:
        raise SourceError("no companies configured (companies.json is empty)")

    def work(b):
        name, provider, slug = b
        try:
            return b, FETCHERS[provider](slug), None
        except Exception as e:
            return b, None, str(e)[:150]

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(work, boards))
    n, ok, failed = 0, 0, []
    for (name, provider, slug), jobs, err in results:
        if jobs is None:
            failed.append("%s (%s)" % (name, err[:40]))
            db.execute("UPDATE companies SET last_status=?, last_checked=? WHERE provider=? AND slug=?",
                       ("error: " + err, NOW(), provider, slug))
            continue
        ok += 1
        for j in jobs:
            pid = "%s:%s:%s" % (provider, slug, j["jid"])
            lane, level, region, flags, tier, cmin, cmax, csrc, ctext, below = classify(j)
            row = db.execute("SELECT first_seen FROM job_postings WHERE id=?", (pid,)).fetchone()
            first = row[0] if row else TODAY
            db.execute("INSERT OR REPLACE INTO job_postings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (pid, name, provider, slug, j["title"], j["location"], j["department"], j["posted_at"],
                        j["url"], ctext, cmin, cmax, csrc, lane, level, region, flags, tier, below,
                        first, TODAY, 1, None, j["desc"]))
        db.execute("UPDATE job_postings SET is_open=0, closed_on=? WHERE provider=? AND slug=? AND is_open=1 AND last_seen<?",
                   (TODAY, provider, slug, TODAY))
        db.execute("UPDATE companies SET last_status='ok', last_count=?, last_checked=? WHERE provider=? AND slug=?",
                   (len(jobs), NOW(), provider, slug))
        n += len(jobs)
    db.execute("DELETE FROM posting_daily WHERE date=?", (TODAY,))
    db.execute("""INSERT INTO posting_daily SELECT ?, company, region, lane, fit_tier, count(*)
                  FROM job_postings WHERE is_open=1 GROUP BY company, region, lane, fit_tier""", (TODAY,))
    db.commit()
    if ok == 0:
        raise SourceError("all %s boards failed, e.g. %s" % (len(boards), "; ".join(failed[:3])))
    return n, "%s of %s boards answered%s" % (ok, len(boards), ("; failed: " + "; ".join(failed[:8])) if failed else "")


# ---------------------------------------------------------------- job-board discovery
SUFFIX = re.compile(r",?\s+(inc|llc|l\.l\.c|corp|corporation|co|company|ltd|limited|lp|l\.p|plc|pbc|usa|us|u\.s\.a|holdings|group|technologies|technology|north america|americas?)\.?$", re.I)


def clean_name(n):
    n = n.strip()
    for _ in range(3):
        n2 = SUFFIX.sub("", n).strip(" ,.")
        if n2 == n:
            break
        n = n2
    return n


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def discover_one(name):
    """Try public job-board APIs for a company name. A board is accepted only when the
    board itself confirms the company name (Greenhouse board name, or the name appearing
    in the board's own posting text for Lever and Ashby)."""
    base = clean_name(name)
    words = re.findall(r"[A-Za-z0-9]+", base.lower())
    if not words:
        return None
    slugs = []
    for s in ("".join(words), "-".join(words)):
        if s not in slugs and len(s) >= 3:
            slugs.append(s)
    target = _norm(base)
    for slug in slugs:
        code, body, _ = http_get("https://boards-api.greenhouse.io/v1/boards/%s" % slug, timeout=30)
        if code == 200:
            try:
                bname = json.loads(body).get("name") or ""
            except ValueError:
                bname = ""
            if bname and (_norm(bname) == target or target in _norm(bname) or _norm(bname) in target):
                return ("greenhouse", slug, bname)
        for provider in ("lever", "ashby"):
            try:
                jobs = FETCHERS[provider](slug)
            except Exception:
                continue
            if jobs:
                sample = " ".join((j["title"] + " " + j["desc"])[:4000] for j in jobs[:5]).lower()
                if base.lower() in sample:
                    return (provider, slug, base)
    return None


def run_discovery(db, names_with_origin):
    todo = []
    known = {_norm(r[0]) for r in db.execute("SELECT name FROM companies")}
    for name, origin in names_with_origin:
        key = _norm(clean_name(name))
        if not key or key in known:
            continue
        known.add(key)
        if db.execute("SELECT 1 FROM discovery_log WHERE name=? AND checked_at>=date('now','-60 day')", (name,)).fetchone():
            continue
        todo.append((name, origin))
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(lambda t: (t, discover_one(t[0])), todo))
    found = 0
    for (name, origin), hit in results:
        if hit:
            provider, slug, bname = hit
            db.execute("INSERT OR IGNORE INTO companies(name, provider, slug, origin, board_name, name_verified) VALUES(?,?,?,?,?,1)",
                       (clean_name(name), provider, slug, origin, bname))
            found += 1
        db.execute("INSERT OR REPLACE INTO discovery_log VALUES(?,?,?,?)",
                   (name, origin, NOW(), ("%s:%s" % hit[:2]) if hit else "no public Greenhouse/Lever/Ashby board found"))
    db.commit()
    return len(todo), found


def src_discover(db):
    seed_companies(db)
    names = []
    path = os.path.join(HERE, "companies_to_discover.txt")
    if os.path.exists(path):
        with open(path) as f:
            names += [(l.strip(), "companies_to_discover.txt") for l in f if l.strip() and not l.startswith("#")]
    names += [(n, "clean_energy_companies.txt") for n in _clean_names()]
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='lca'").fetchone():
        q = """SELECT EMPLOYER_NAME, count(*) c FROM lca
               WHERE WORKSITE_STATE='MA' AND CASE_STATUS LIKE 'Certified%' AND EMPLOYER_NAME IS NOT NULL
               GROUP BY upper(EMPLOYER_NAME) ORDER BY c DESC LIMIT ?"""
        names += [(r[0].title(), "lca_top_ma_sponsors") for r in db.execute(q, (CFG["lca_discover_top_n"],))]
    tried, found = run_discovery(db, names)
    return found, "checked %s company names, %s new boards confirmed" % (tried, found)


# ---------------------------------------------------------------- export / report / status
def export_all(db, outdir=None):
    outdir = outdir or os.path.join(HERE, "exports")
    os.makedirs(outdir, exist_ok=True)
    objs = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    written = []
    for t in objs:
        cur = db.execute('SELECT * FROM "%s"' % t)
        cols = [d[0] for d in cur.description]
        path = os.path.join(outdir, t + ".csv")
        n = 0
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for row in cur:
                w.writerow(row)
                n += 1
        written.append((t, n))
    return outdir, written


def _table(rows, headers):
    if not rows:
        return "_No rows._\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if v is None else str(v).replace("|", "/") for v in r) + " |")
    return "\n".join(out) + "\n"


def _has(db, t):
    return db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone() is not None


def _src_note(db, source):
    r = db.execute("SELECT status, run_at, detail FROM source_status WHERE source=? ORDER BY run_at DESC LIMIT 1", (source,)).fetchone()
    if not r:
        return "_Source `%s` has not been run yet._\n" % source
    return "_Source `%s`: last run %s, status %s. %s_\n" % (source, r[1], r[0], (r[2] or "")[:200])


def build_report(db):
    L = []
    A = L.append
    A("# Where to aim: Boston and East Coast job market\n")
    A("Generated %s from `jobmarket.db`. Every figure is a direct query of public-source rows; "
      "sections with no data say so and name the source status. Fit tiers are keyword rules from `config.json`, not a judgment.\n" % NOW())

    A("## 1. Employers with open roles in your lanes (live postings)\n")
    A(_src_note(db, "jobs"))
    rows = db.execute("""SELECT company, open_target_boston, open_target_lane, open_boston, open_roles_total,
                                first_seen_last_30d, closed_last_30d
                         FROM v_company_hiring WHERE open_target_lane>0
                         ORDER BY open_target_boston DESC, open_target_lane DESC LIMIT 40""").fetchall()
    A(_table(rows, ["Company", "Target roles, Boston", "Target roles, all US", "All open, Boston", "All open", "New in 30d", "Closed in 30d"]))

    A("## 2. Open target roles by lane and region\n")
    rows = db.execute("""SELECT lane, region, count(*) FROM job_postings
                         WHERE is_open=1 AND fit_tier IN ('target','adjacent') GROUP BY lane, region
                         ORDER BY lane, count(*) DESC""").fetchall()
    A(_table(rows, ["Lane", "Region", "Open roles"]))

    A("## 3. Target roles open now in the Boston area\n")
    rows = db.execute("""SELECT company, title, location, lane, comp_text, url FROM v_target_roles
                         WHERE region='boston_area' LIMIT 100""").fetchall()
    A(_table(rows, ["Company", "Title", "Location", "Lane", "Pay as posted", "Link"]))

    A("## 4. Why roles in your lanes were excluded\n")
    rows = db.execute("""SELECT CASE WHEN restriction_flags<>'' THEN restriction_flags WHEN level_flag<>'' THEN level_flag ELSE region END reason,
                                count(*) FROM job_postings WHERE is_open=1 AND fit_tier='excluded' GROUP BY reason ORDER BY 2 DESC""").fetchall()
    A(_table(rows, ["Reason", "Open roles"]))

    A("## 5. H-1B filings: who files in Massachusetts for titles in your lanes (DOL LCA data)\n")
    A("An LCA (Labor Condition Application) is the form an employer files with the Department of Labor before an H-1B petition. "
      "A certified LCA shows the employer has sponsored that kind of role; it is not proof of a current opening.\n")
    A(_src_note(db, "lca"))
    if _has(db, "lca"):
        kws = sorted({k for name, ks in CFG["lanes"].items() for k in ks})
        like = " OR ".join("lower(JOB_TITLE) LIKE ?" for _ in kws)
        data = db.execute("""SELECT EMPLOYER_NAME, wage_from_annualized FROM lca
                             WHERE WORKSITE_STATE='MA' AND CASE_STATUS LIKE 'Certified%%' AND (%s)""" % like,
                          ["%" + k + "%" for k in kws]).fetchall()
        agg = {}
        for emp, w in data:
            a = agg.setdefault((emp or "").upper(), [emp, 0, []])
            a[1] += 1
            if w:
                a[2].append(w)
        rows = sorted(agg.values(), key=lambda a: -a[1])[:40]
        A(_table([(a[0], a[1], int(statistics.median(a[2])) if a[2] else None) for a in rows],
                 ["Employer", "Certified LCAs, lane titles, MA worksite", "Median offered wage (annualized, USD)"]))
        rows = db.execute("""SELECT EMPLOYER_NAME, count(*) c FROM lca WHERE WORKSITE_STATE='MA' AND CASE_STATUS LIKE 'Certified%'
                             GROUP BY upper(EMPLOYER_NAME) ORDER BY c DESC LIMIT 25""").fetchall()
        A("\nTop Massachusetts-worksite filers, all job titles:\n")
        A(_table(rows, ["Employer", "Certified LCAs"]))

    A("## 6. Pay and employment by occupation, Boston metro (BLS OEWS)\n")
    A(_src_note(db, "oews"))
    socs = [s.replace("-", "") for s in CFG["report_soc_codes"]]
    rows = db.execute("""SELECT occupation_code, occupation_name, datatype, value_text, year FROM oews
                         WHERE area_name LIKE 'Boston-Cambridge-Newton%%' AND occupation_code IN (%s)
                         ORDER BY occupation_code, datatype_code""" % ",".join("?" * len(socs)), socs).fetchall()
    A(_table(rows, ["SOC code", "Occupation", "Measure", "Value", "Year"]))

    A("## 7. Boston metro labor market trend (BLS LAUS)\n")
    A(_src_note(db, "laus"))
    rows = db.execute("""SELECT area_name, measure, year, period, value FROM laus
                         WHERE area_name LIKE 'Boston-Cambridge-Newton%' AND seasonal='U'
                         ORDER BY year DESC, period DESC, measure_code LIMIT 52""").fetchall()
    A(_table(rows, ["Area", "Measure", "Year", "Period", "Value"]))

    A("## 8. Jobs by industry, latest month against a year earlier (BLS CES, Massachusetts areas)\n")
    A(_src_note(db, "ces"))
    rows = db.execute("""WITH latest AS (SELECT series_id, max(year*100+CAST(substr(period,2) AS INT)) ym FROM ces
                                          WHERE data_type_code='01' AND seasonal='U' AND period<>'M13' AND area_name LIKE 'Boston%' GROUP BY series_id)
                         SELECT c.area_name, c.industry_name, c.year, c.period, c.value, p.value,
                                round(100.0*(c.value-p.value)/p.value,1)
                         FROM latest l JOIN ces c ON c.series_id=l.series_id AND c.year*100+CAST(substr(c.period,2) AS INT)=l.ym
                         JOIN ces p ON p.series_id=c.series_id AND p.year=c.year-1 AND p.period=c.period
                         WHERE p.value>0 ORDER BY 7 DESC LIMIT 40""").fetchall()
    A(_table(rows, ["Area", "Industry", "Year", "Period", "Jobs (thousands)", "Year earlier", "Change %"]))

    A("## 9. Openings, hires and quits, Massachusetts (BLS JOLTS)\n")
    A(_src_note(db, "jolts"))
    rows = db.execute("""SELECT dataelement, ratelevel, year, period, value FROM jolts
                         WHERE state_code='25' AND seasonal='S' AND industry_code='000000'
                         ORDER BY year DESC, period DESC, dataelement_code LIMIT 40""").fetchall()
    A(_table(rows, ["Measure", "Rate or level", "Year", "Period", "Value"]))

    A("## 10. Hires by industry, Boston-area counties (Census QWI)\n")
    A("County codes: 025 Suffolk (Boston), 017 Middlesex (Cambridge), 021 Norfolk. HirA = all hires in the quarter; EarnHirAS = average monthly earnings of stable new hires.\n")
    A(_src_note(db, "qwi"))
    rows = db.execute("""SELECT county, time, industry, max(CASE WHEN variable='HirA' THEN value END),
                                max(CASE WHEN variable='Emp' THEN value END), max(CASE WHEN variable='EarnHirAS' THEN value END)
                         FROM qwi WHERE county IN ('025','017','021') AND time=(SELECT max(time) FROM qwi)
                         GROUP BY county, time, industry ORDER BY county, 4 DESC""").fetchall()
    A(_table(rows, ["County", "Quarter", "NAICS sector", "Hires", "Employment", "Avg monthly earnings, new hires"]))

    A("## Source status\n")
    rows = db.execute("""SELECT s.source, s.publisher, (SELECT status||' '||run_at FROM source_status x WHERE x.source=s.source ORDER BY run_at DESC LIMIT 1),
                                (SELECT detail FROM source_status x WHERE x.source=s.source ORDER BY run_at DESC LIMIT 1), s.url
                         FROM sources s""").fetchall()
    A(_table(rows, ["Source", "Publisher", "Last run", "Detail", "URL"]))
    A("\nNot covered: LinkedIn, Indeed and Glassdoor postings (their terms forbid automated collection), "
      "employer career sites that are not on Greenhouse, Lever or Ashby (for example Workday-hosted sites), and company financial reports.\n")
    path = os.path.join(HERE, "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return path


# ---------------------------------------------------------------- Excel workbook (stdlib writer)
from xml.sax.saxutils import escape as _xesc

_BADXML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _sheet_xml(headers, rows, link_cols=()):
    widths = [min(60, max(10, len(str(h)) + 2)) for h in headers]
    out = []
    for ri, row in enumerate([headers] + list(rows), start=1):
        cells = []
        for ci, v in enumerate(row):
            if v is None or v == "":
                continue
            ref = "%s%d" % (_col(ci), ri)
            if ri == 1:
                cells.append('<c r="%s" t="inlineStr" s="1"><is><t>%s</t></is></c>' % (ref, _xesc(str(v))))
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                cells.append('<c r="%s"><v>%r</v></c>' % (ref, v))
            else:
                t = _BADXML.sub(" ", str(v))[:32000]
                if ci in link_cols and t.startswith("http") and len(t) < 250 and '"' not in t:
                    cells.append('<c r="%s" s="2"><f>HYPERLINK("%s","Open posting")</f></c>' % (ref, _xesc(t)))
                else:
                    if ri < 200 and ci < len(widths):
                        widths[ci] = min(60, max(widths[ci], len(t) + 2))
                    cells.append('<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, _xesc(t)))
        out.append('<row r="%d">%s</row>' % (ri, "".join(cells)))
    n = len(out)
    cols = "".join('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (i + 1, i + 1, w) for i, w in enumerate(widths))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            '<cols>%s</cols><sheetData>%s</sheetData><autoFilter ref="A1:%s%d"/></worksheet>'
            % (cols, "".join(out), _col(len(headers) - 1), max(n, 1)))


def write_xlsx(path, sheets):
    """sheets: list of (name, headers, rows, link_cols)."""
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1) for i in range(len(sheets)))
                   + '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (_xesc(n[:31]), i + 1, i + 1) for i, (n, _, _, _) in enumerate(sheets))
                   + '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1) for i in range(len(sheets)))
                   + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>' % (len(sheets) + 1))
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font>'
                   '<font><u/><sz val="11"/><color rgb="FF0563C1"/><name val="Calibri"/></font></fonts>'
                   '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
                   '<fill><patternFill patternType="solid"><fgColor rgb="FFDDE7F3"/></patternFill></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
                   '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs></styleSheet>')
        for i, (name, headers, rows, links) in enumerate(sheets):
            z.writestr("xl/worksheets/sheet%d.xml" % (i + 1), _sheet_xml(headers, rows, links))
    os.replace(tmp, path)


def _pivot(rows, key_n, label_order):
    """rows: (key..., label, value). Returns rows of key + one column per label."""
    agg = {}
    for r in rows:
        agg.setdefault(tuple(r[:key_n]), {})[r[key_n]] = r[key_n + 1]
    return [list(k) + [v.get(l) for l in label_order] for k, v in agg.items()]


def _source_rows(db):
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    def span(sql):
        try:
            r = db.execute(sql).fetchone()
            return "%s to %s" % (r[0], r[1]) if r and r[0] is not None else "no data loaded"
        except sqlite3.Error:
            return "no data loaded"

    ym = "min(year||'-'||period), max(year||'-'||period)"
    cover = {
        "laus": span("SELECT %s FROM laus WHERE period<>'M13'" % ym),
        "ces": span("SELECT %s FROM ces WHERE period<>'M13'" % ym),
        "jolts": span("SELECT %s FROM jolts WHERE period<>'M13'" % ym),
        "oews": span("SELECT min(year), max(year) FROM oews"),
        "qcew": span("SELECT min(year||'-Q'||qtr), max(year||'-Q'||qtr) FROM qcew"),
        "acs": span("SELECT min(year), max(year) FROM acs"),
        "qwi": span("SELECT min(time), max(time) FROM qwi"),
        "cbp": span("SELECT min(year), max(year) FROM cbp"),
        "lca": span("SELECT min(DECISION_DATE), max(DECISION_DATE) FROM lca") if _has(db, "lca") else "no data loaded",
        "jobs": span("SELECT min(first_seen), max(last_seen) FROM job_postings") + " (dates the collector saw postings)",
    }
    used_in = {
        "laus": "Boston labor force", "ces": "MA jobs by industry", "jolts": "MA openings and hires",
        "oews": "Wages by occupation", "qcew": "Boston industries", "acs": "none yet (CSV only once loaded)",
        "qwi": "none yet (CSV only once loaded)", "cbp": "none yet (CSV only once loaded)",
        "lca": "H1B sponsors MA; H1B filings lane titles; H1B filings MA all",
        "jobs": "Target roles; Company hiring; All open postings",
    }
    tables = {"laus": "laus", "ces": "ces", "jolts": "jolts", "oews": "oews", "qcew": "qcew", "acs": "acs",
              "qwi": "qwi", "cbp": "cbp", "lca": "lca", "jobs": "job_postings"}
    src_rows = []
    for source, publisher, desc, url in q("SELECT source, publisher, description, url FROM sources"):
        last_ok = q("SELECT max(run_at) FROM source_status WHERE source=? AND status='ok'", source)[0][0]
        last = q("SELECT status FROM source_status WHERE source=? ORDER BY run_at DESC LIMIT 1", source)
        t = tables.get(source)
        n = q('SELECT count(*) FROM "%s"' % t)[0][0] if t and _has(db, t) else 0
        days = CFG["refresh_days"].get(source, 7)
        src_rows.append([publisher, desc, url, used_in.get(source, ""), cover.get(source, ""), n,
                         last_ok or "never loaded", last[0][0] if last else "never run",
                         "every day" if days == 0 else "every %s days" % days, t or ""])
    return src_rows


def _ym(year, period):
    return "%s-%s" % (year, period[1:])


SECTOR_LABELS = {'11': 'Agriculture, forestry, fishing', '21': 'Mining', '22': 'Utilities', '23': 'Construction', '31-33': 'Manufacturing', '42': 'Wholesale trade', '44-45': 'Retail (stores and e-commerce)', '48-49': 'Transportation and warehousing', '51': 'Information (software, media, telecom)', '52': 'Finance and insurance', '53': 'Real estate and rental', '54': 'Professional and technical services (consulting, IT services, R&D)', '55': 'Corporate headquarters and holding companies', '56': 'Staffing, facilities and business support services', '61': 'Education', '62': 'Health care and social assistance', '71': 'Arts, entertainment and recreation', '72': 'Hotels and restaurants', '81': 'Other services (repair, personal care, nonprofits)', '92': 'Government'}
NAICS_SECTORS = {'11': 'Agriculture, forestry, fishing', '21': 'Mining', '22': 'Utilities', '23': 'Construction', '31': 'Manufacturing', '32': 'Manufacturing', '33': 'Manufacturing', '42': 'Wholesale trade', '44': 'Retail (stores and e-commerce)', '45': 'Retail (stores and e-commerce)', '48': 'Transportation and warehousing', '49': 'Transportation and warehousing', '51': 'Information (software, media, telecom)', '52': 'Finance and insurance', '53': 'Real estate and rental', '54': 'Professional and technical services (consulting, IT services, R&D)', '55': 'Corporate headquarters and holding companies', '56': 'Staffing, facilities and business support services', '61': 'Education', '62': 'Health care and social assistance', '71': 'Arts, entertainment and recreation', '72': 'Hotels and restaurants', '81': 'Other services (repair, personal care, nonprofits)', '92': 'Government'}
CES_RENAME = {'Management of Companies and Enterprises': SECTOR_LABELS['55'], 'Professional, Scientific, and Technical Services': SECTOR_LABELS['54'], 'Administrative and Support and Waste Management and Remediation Services': SECTOR_LABELS['56'], 'Accommodation and Food Services': SECTOR_LABELS['72'], 'Private Educational Services': 'Education (private)', 'Arts, Entertainment, and Recreation': SECTOR_LABELS['71'], 'Information': SECTOR_LABELS['51'], 'Financial Activities': 'Finance, insurance and real estate', 'Retail Trade': SECTOR_LABELS['44-45']}
JOLTS_RENAME = {'Accommodation and food services': SECTOR_LABELS['72'], 'Retail trade': SECTOR_LABELS['44-45'], 'Information': SECTOR_LABELS['51'], 'Arts, entertainment, and recreation': SECTOR_LABELS['71'], 'Real estate and rental and leasing': SECTOR_LABELS['53'], 'Private educational services': 'Education (private)', 'Wholesale trade': SECTOR_LABELS['42']}
CLEAN_LABEL = "Clean and renewable energy"
CLEAN_NAICS = ("221114", "221115", "221116", "221117", "33591", "333611")
CLEAN_NAME_RX = re.compile(r"\bsolar\b|renewabl|wind (energy|power)|\bbatter(y|ies)\b|hydrogen|clean energy|energy storage|photovolt|geotherm", re.I)


def _clean_names():
    path = os.path.join(HERE, "clean_energy_companies.txt")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


CLEAN_LIST = [x for x in (re.sub(r"[^a-z0-9]", "", n.lower()) for n in _clean_names()) if len(x) >= 5]


def is_clean_energy(employer, naics=""):
    e = employer or ""
    k = re.sub(r"[^a-z0-9]", "", e.lower())
    return (naics or "").startswith(CLEAN_NAICS) or bool(CLEAN_NAME_RX.search(e)) or any(k.startswith(n) for n in CLEAN_LIST)


def sector_of(employer, naics):
    if is_clean_energy(employer, naics):
        return CLEAN_LABEL
    return NAICS_SECTORS.get((naics or "")[:2])


CES_AGGREGATES = {"00000000", "05000000", "06000000", "07000000", "08000000"}


def build_trends(db, asof):
    """Trend tables. Every number is a count or a percent change computed from loaded rows."""
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    pct = lambda now, then: round(100.0 * (now - then) / then, 1) if now is not None and then else None
    T = {}
    # which tracked company boards exist, and each one's industry as stated on its own H-1B filings
    tracked = {_norm(clean_name(n)): n for (n,) in q("SELECT DISTINCT name FROM companies WHERE last_status='ok'")}
    ci = {}
    if _has(db, "lca"):
        votes = {}
        for emp, n2, n in q("SELECT EMPLOYER_NAME, NAICS_CODE, count(*) FROM lca WHERE EMPLOYER_NAME IS NOT NULL GROUP BY 1, 2"):
            k = _norm(clean_name(emp))
            lab = sector_of(emp, n2)
            if k in tracked and lab:
                votes.setdefault(k, {}).setdefault(lab, 0)
                votes[k][lab] += n
        ci = {tracked[k]: max(v, key=v.get) for k, v in votes.items()}
    for k, name in tracked.items():
        if is_clean_energy(name):
            ci[name] = CLEAN_LABEL
    T["company_industry"] = ci
    T["tracked_companies"] = len(tracked)
    # --- industries: BLS CES, Boston metro, same month across years (removes seasonality)
    ser = {}
    for code, name, y, p, v in q("SELECT industry_code, industry_name, year, period, value FROM ces WHERE area_name='Boston-Cambridge-Newton, MA-NH' "
                                 "AND data_type_code='01' AND seasonal='U' AND period<>'M13' AND value IS NOT NULL"):
        ser.setdefault((code, name), {})[(y, int(p[1:]))] = v
    ind, latest = [], None
    if ser:
        latest = max(max(d) for d in ser.values())
        ly, lm = latest
        for (code, name), d in ser.items():
            now = d.get(latest)
            if now is None:
                continue
            ind.append({"name": CES_RENAME.get(name, name), "raw": name, "agg": code in CES_AGGREGATES, "sub": not code.endswith("000000"), "now": now,
                        "d1": round((now - d[(ly - 1, lm)]) * 1000) if d.get((ly - 1, lm)) is not None else None,
                        "y1": pct(now, d.get((ly - 1, lm))), "y3": pct(now, d.get((ly - 3, lm))), "y2019": pct(now, d.get((2019, lm))),
                        "spark": [d.get((yy, lm)) for yy in range(min(k[0] for k in d), ly + 1) if d.get((yy, lm)) is not None]})
        ind.sort(key=lambda r: -(r["y1"] if r["y1"] is not None else -999))
    T["industries"] = {"month": "%s-%02d" % latest if latest else "", "rows": ind}
    # --- detailed industries: BLS QCEW, Boston metro, private sector, 3-digit NAICS
    det, det_q = [], ""
    if _has(db, "qcew") and _has(db, "qcew_industry_titles"):
        lq = q("SELECT year, qtr FROM qcew WHERE area_fips='C1446' AND own_code='5' AND agglvl_code='45' GROUP BY year, qtr "
               "HAVING sum(CAST(month3_emplvl AS INT))>0 ORDER BY year DESC, qtr DESC LIMIT 1")
        if lq:
            det_q = "%s Q%s" % lq[0]
            for title, emp, epct, wage, wpct in q(
                    "SELECT t.title, q.month3_emplvl, q.oty_month3_emplvl_pct_chg, q.avg_wkly_wage, q.oty_avg_wkly_wage_pct_chg FROM qcew q "
                    "LEFT JOIN qcew_industry_titles t ON t.code=q.industry_code WHERE q.area_fips='C1446' AND q.own_code='5' AND q.agglvl_code='45' "
                    "AND q.year=? AND q.qtr=?", *lq[0]):
                emp, epct, wage, wpct = num(emp), num(epct), num(wage), num(wpct)
                if emp and emp >= 2000 and epct is not None:
                    det.append({"name": {"Management of companies and enterprises": SECTOR_LABELS["55"]}.get(re.sub(r"^NAICS \d+ ", "", title or ""), re.sub(r"^NAICS \d+ ", "", title or "")), "emp": emp, "epct": epct, "wage": wage, "wpct": wpct})
            det.sort(key=lambda r: -r["epct"])
    T["detail"] = {"quarter": det_q, "rows": det}
    # --- national demand by industry: BLS JOLTS openings and hires rates
    jl = {}
    for ind_name, el, y, p, v in q("SELECT industry, dataelement_code, year, period, value FROM jolts WHERE state_code='00' AND seasonal='S' "
                                   "AND ratelevel_code='R' AND sizeclass_code='00' AND dataelement_code IN ('JO','HI','QU','LD') AND period<>'M13' AND value IS NOT NULL"):
        jl.setdefault(ind_name, {}).setdefault(el, {})[(y, int(p[1:]))] = v
    jrows, jmonth = [], None
    if jl:
        jmonth = max(max(d.get("JO", {(0, 0): 0})) for d in jl.values())
        for name, d in jl.items():
            jo = d.get("JO", {})
            if jmonth in jo:
                prev = jo.get((jmonth[0] - 1, jmonth[1]))
                jrows.append({"name": JOLTS_RENAME.get(name, name), "raw": name, "jo": jo[jmonth], "jo_prev": prev, "chg": round(jo[jmonth] - prev, 1) if prev is not None else None,
                              "hi": d.get("HI", {}).get(jmonth), "qu": d.get("QU", {}).get(jmonth), "ld": d.get("LD", {}).get(jmonth),
                              "spark": [jo[k] for k in sorted(jo) if k[1] == jmonth[1]]})
        jrows.sort(key=lambda r: -r["jo"])
    T["jolts"] = {"month": "%s-%02d" % jmonth if jmonth else "", "rows": jrows}
    # --- H-1B filings (DOL LCA), Massachusetts worksites, certified, by calendar quarter of decision
    T["lca"] = None
    if _has(db, "lca"):
        lanes = CFG["lanes"]
        excl = CFG.get("title_exclude", [])

        def lane_of(title):
            t = " " + (title or "").lower() + " "
            if any(k in t for k in excl):
                return None
            for name, kws in lanes.items():
                if any(k in t for k in kws):
                    return name
            return None
        by = {"lane": {}, "soc": {}, "sector": {}, "employer": {}, "employer_lane": {}}
        disp, quarters = {}, set()
        lane_rows, emp_w = [], {}
        for emp, title, soc, naics, dd, wg in q("SELECT EMPLOYER_NAME, JOB_TITLE, SOC_TITLE, NAICS_CODE, DECISION_DATE, wage_from_annualized FROM lca "
                                           "WHERE WORKSITE_STATE='MA' AND CASE_STATUS LIKE 'Certified%' AND DECISION_DATE GLOB '[12][0-9][0-9][0-9]-*'"):
            qk = "%s Q%s" % (dd[:4], (int(dd[5:7]) - 1) // 3 + 1)
            quarters.add(qk)
            ek = (emp or "").upper().strip()
            disp.setdefault(ek, (emp or "").strip())
            ln = lane_of(title)
            if wg:
                emp_w.setdefault(ek, []).append(wg)
            if ln:
                lane_rows.append([ek, sector_of(emp, naics) or "Not classified", ln, qk, wg])
            for dim, key in (("soc", soc), ("sector", sector_of(emp, naics) or "Not classified"), ("employer", ek)):
                if key:
                    by[dim].setdefault(key, {}).setdefault(qk, 0)
                    by[dim][key][qk] += 1
            if ln:
                for dim, key in (("lane", ln), ("employer_lane", ek)):
                    by[dim].setdefault(key, {}).setdefault(qk, 0)
                    by[dim][key][qk] += 1
        qs = sorted(quarters)

        def top(dim, n, names=None):
            rows = [{"name": (names or {}).get(k, k), "c": [d.get(x, 0) for x in qs]} for k, d in by[dim].items()]
            rows.sort(key=lambda r: -sum(r["c"][-4:]))
            return rows[:n]
        T["lca"] = {"quarters": qs, "lane": top("lane", 20), "soc": top("soc", 40), "sector": top("sector", 25),
                    "employer": top("employer", 40, disp), "employer_lane": top("employer_lane", 40, disp),
                    "lane_rows": lane_rows,
                    "emp_totals": {k: [disp[k], sum(by["employer"][k].values()), int(statistics.median(emp_w[k])) if emp_w.get(k) else None,
                                       tracked.get(_norm(clean_name(disp[k])))]
                                   for k in {r[0] for r in lane_rows}}}
    # --- industry scorecard: one row per NAICS sector, metrics from four sources side by side
    SECT = {k: v for k, v in SECTOR_LABELS.items() if k not in ('11', '21', '22', '92')}
    JMAP = {"23": "Construction", "31-33": "Manufacturing", "42": "Wholesale trade", "44-45": "Retail trade",
            "48-49": "Transportation, warehousing, and utilities", "51": "Information", "52": "Finance and insurance",
            "53": "Real estate and rental and leasing", "54": "Professional and business services",
            "55": "Professional and business services", "56": "Professional and business services",
            "61": "Private educational services", "62": "Health care and social assistance",
            "71": "Arts, entertainment, and recreation", "72": "Accommodation and food services", "81": "Other services"}
    grp = lambda c: "31-33" if c in ("31", "32", "33") else "44-45" if c in ("44", "45") else "48-49" if c in ("48", "49") else c
    SECT["CE"] = CLEAN_LABEL
    sc = {k: {"name": v} for k, v in SECT.items()}
    sc_q = ""
    if _has(db, "qcew"):
        lq2 = q("SELECT year, qtr FROM qcew WHERE area_fips='C1446' AND own_code='5' AND agglvl_code='44' GROUP BY year, qtr "
                "HAVING sum(CAST(month3_emplvl AS INT))>0 ORDER BY year DESC, qtr DESC LIMIT 1")
        if lq2:
            sc_q = "%s Q%s" % lq2[0]
            for code, emp, epct, wage, wpct in q("SELECT industry_code, month3_emplvl, oty_month3_emplvl_pct_chg, avg_wkly_wage, oty_avg_wkly_wage_pct_chg "
                                                 "FROM qcew WHERE area_fips='C1446' AND own_code='5' AND agglvl_code='44' AND year=? AND qtr=?", *lq2[0]):
                if code in sc and num(emp):
                    sc[code].update(emp=num(emp), epct=num(epct), wage=num(wage), wpct=num(wpct))
    # jobs and 1-year change come from the same CES series as the "Jobs by industry" table, so the two tables agree
    CESMAP = {"23": "Mining, Logging and Construction", "31-33": "Manufacturing", "42": "Wholesale Trade", "44-45": "Retail Trade",
              "48-49": "Transportation, Warehousing, and Utilities", "51": "Information", "52": "Financial Activities",
              "53": "Financial Activities", "54": "Professional, Scientific, and Technical Services",
              "55": "Management of Companies and Enterprises",
              "56": "Administrative and Support and Waste Management and Remediation Services",
              "61": "Private Educational Services", "62": "Health Care and Social Assistance",
              "71": "Arts, Entertainment, and Recreation", "72": "Accommodation and Food Services", "81": "Other Services"}
    ces_raw = {r["raw"]: r for r in ind}
    for k in sc:
        c = ces_raw.get(CESMAP.get(k))
        if c:
            sc[k].update(emp=round(c["now"] * 1000), epct=c["y1"], ed1=c["d1"])
        else:
            sc[k].pop("emp", None)
            sc[k].pop("epct", None)
    jby = {r["raw"]: r for r in jrows}
    for k in sc:
        j = jby.get(JMAP.get(k))
        if j:
            sc[k].update(jo=j["jo"], jo_chg=j["chg"])
    lca_span = ""
    if _has(db, "lca"):
        lanes_kw = [k for ks in CFG["lanes"].values() for k in ks]
        excl2 = CFG.get("title_exclude", [])
        rowsl = q("SELECT NAICS_CODE, JOB_TITLE, wage_from_annualized, DECISION_DATE, EMPLOYER_NAME FROM lca WHERE WORKSITE_STATE='MA' "
                  "AND CASE_STATUS LIKE 'Certified%' AND DECISION_DATE GLOB '[12][0-9][0-9][0-9]-*'")
        qk = lambda dd: "%s Q%s" % (dd[:4], (int(dd[5:7]) - 1) // 3 + 1)
        last4 = sorted({qk(r[3]) for r in rowsl})[-4:]
        lca_span = "%s to %s" % (last4[0], last4[-1]) if last4 else ""
        wages_l = {}
        for naics, title, w, dd, emp_n in rowsl:
            k = "CE" if is_clean_energy(emp_n, naics) else grp((naics or "")[:2])
            if k not in sc or qk(dd) not in last4:
                continue
            sc[k]["lca_all"] = sc[k].get("lca_all", 0) + 1
            t = " " + (title or "").lower() + " "
            if any(x in t for x in lanes_kw) and not any(x in t for x in excl2):
                sc[k]["lca_lane"] = sc[k].get("lca_lane", 0) + 1
                if w:
                    wages_l.setdefault(k, []).append(w)
        for k, ws in wages_l.items():
            if len(ws) >= 5:
                sc[k]["lane_wage"] = int(statistics.median(ws))
    rank_keys = ["lca_lane", "lane_wage", "wage", "epct", "jo_chg"]
    for key in rank_keys:
        vals = sorted((r[key] for r in sc.values() if r.get(key) is not None), reverse=True)
        for r in sc.values():
            if r.get(key) is not None:
                r.setdefault("_ranks", []).append(vals.index(r[key]) + 1)
    out_sc = []
    for r in sc.values():
        rk = r.pop("_ranks", [])
        r["n_metrics"] = len(rk)
        r["avg_rank"] = round(sum(rk) / len(rk), 1) if len(rk) >= 4 else None
        if r.get("emp") or r.get("lca_all"):
            out_sc.append(r)
    out_sc.sort(key=lambda r: (r["avg_rank"] is None, r["avg_rank"] or 0))
    T["scorecard"] = {"ces_month": T["industries"]["month"], "quarter": sc_q, "lca_span": lca_span, "jolts_month": T["jolts"]["month"], "rows": out_sc}
    # --- live postings: when the currently open lane roles were posted, and who posted most in the last 30 days
    cut = (dt.date.fromisoformat(asof) - dt.timedelta(days=30)).isoformat()
    months = {}
    for lane, ym, n in q("SELECT lane, substr(posted_at,1,7), count(*) FROM job_postings WHERE is_open=1 AND fit_tier IN ('target','adjacent') "
                         "AND posted_at GLOB '[12][0-9][0-9][0-9]-[01][0-9]*' GROUP BY 1,2"):
        months.setdefault(lane, {})[ym] = n
    all_m = sorted({m for d in months.values() for m in d})[-12:]
    T["post_months"] = {"months": all_m, "rows": sorted(({"name": l, "c": [d.get(m, 0) for m in all_m]} for l, d in months.items()), key=lambda r: -sum(r["c"]))}
    T["post_recent"] = [{"company": c, "recent": r, "recent_boston": rb, "open": o} for c, r, rb, o in q(
        "SELECT company, sum(substr(posted_at,1,10)>=?), sum(substr(posted_at,1,10)>=? AND region='boston_area'), count(*) FROM job_postings "
        "WHERE is_open=1 AND fit_tier IN ('target','adjacent') AND posted_at GLOB '[12][0-9][0-9][0-9]-[01][0-9]*' GROUP BY company HAVING sum(substr(posted_at,1,10)>=?)>0 "
        "ORDER BY 2 DESC LIMIT 25", cut, cut, cut)]
    T["daily"] = [[d, n, t] for d, n, t in q("SELECT date, sum(open_count), sum(CASE WHEN fit_tier IN ('target','adjacent') THEN open_count ELSE 0 END) FROM posting_daily GROUP BY date ORDER BY date")]
    return T


# Skills vocabulary for matching posting text against the user's CV. "have" = stated on the CV or confirmed by the user;
# "other" = commonly requested skills that are not in the CV facts on file. Edit freely.
CV_SKILLS = [
    ("SQL", r"\bsql\b"), ("Python", r"\bpython\b"),
    ("Dashboards and BI (Looker, Power BI, Tableau)", r"looker|power ?bi|tableau|dashboards?|business intelligence"),
    ("Data analysis", r"data analysis|analytics|analy[sz]e data|data[- ]driven"),
    ("Excel", r"\bexcel\b|spreadsheets?"),
    ("Salesforce", r"salesforce"), ("Jira and Confluence", r"\bjira\b|confluence"),
    ("Agile and Scrum", r"\bagile\b|\bscrum\b|sprints?\b"),
    ("Git and CI/CD", r"\bgit\b|github|gitlab|ci/cd|jenkins|continuous integration"),
    ("Enterprise and Fortune 500 customers", r"enterprise (customers?|clients?|accounts?)|fortune ?(500|100)|strategic (accounts?|customers?)|large enterprises?"),
    ("SaaS", r"\bsaas\b"),
    ("AI and machine learning products", r"\bai\b|machine learning|\bml\b|\bllms?\b|generative"),
    ("Building with LLMs (agents, prompts)", r"ai agents?|agentic|prompt engineering|\brag\b|llm applications?"),
    ("Deployment and implementation", r"implementations?|deploy(ment|ments|ing)?\b|onboarding|roll[- ]?outs?"),
    ("Configuration and integrations", r"configur(e|ation|ing)|integrations?"),
    ("Customer-facing work", r"(customer|client)[- ]facing|work(ing)? (directly )?with (customers|clients)"),
    ("Stakeholder management", r"stakeholders?"),
    ("Executive communication", r"executive[- ](level|presentations?|communication|stakeholders|audiences?|sponsors?)|c-suite|c-level|\bqbrs?\b|business reviews?"),
    ("Requirements and user stories", r"requirements|user stories"),
    ("Project and program management", r"project management|program management|manage (multiple )?projects"),
    ("Cross-functional work", r"cross[- ]functional"),
    ("Process mapping and improvement", r"business process|process (mapping|improvement|design|optimization)"),
    ("Mentoring and team leadership", r"mentor(ing|ship)?|coach(ing)?\b|lead(ing)? (a )?teams?"),
    ("Documentation and knowledge base", r"documentation|knowledge base|playbooks?|runbooks?"),
    ("Security operations background", r"cyber ?security|security operations|\bsoc\b|fraud|threat"),
    ("Financial services exposure", r"financial services|banking|\bbanks?\b|fintech"),
    ("HR tech and recruiting", r"\bhris\b|talent acquisition|recruiting (software|tech)|hr tech|human capital"),
    ("Palantir Foundry", r"palantir|\bfoundry\b"),
    ("MongoDB and NoSQL", r"mongodb|nosql"),
    ("MBA", r"\bmba\b"),
    ("Startup-to-scale experience", r"start-?ups?|fast[- ]paced|high[- ]growth|scal(e|ing) (a |the )?(team|company|business)"),
]
OTHER_SKILLS = [
    ("Cloud platforms (AWS, Azure, GCP)", r"\baws\b|\bazure\b|\bgcp\b|google cloud"),
    ("Data warehouses (Snowflake, BigQuery, dbt)", r"snowflake|bigquery|redshift|\bdbt\b|data warehouse"),
    ("Data engineering (Spark, ETL, pipelines)", r"\bspark\b|pyspark|\betl\b|data pipelines?|data engineering"),
    ("Kubernetes and Docker", r"kubernetes|\bk8s\b|docker"),
    ("APIs (REST)", r"\bapis?\b|\brest(ful)?\b"),
    ("Software engineering (Java, Go, TypeScript)", r"\bjava\b|typescript|javascript|golang|\bc\+\+|\brust\b|software engineering experience"),
    ("Pre-sales (demos, proofs of concept)", r"pre-?sales|proofs? of concept|\bpocs?\b|\bdemos?\b|solution selling|technical sales"),
    ("Sales quota and pipeline", r"\bquota\b|pipeline generation|closing deals|sales cycle"),
    ("Management consulting background", r"management consult(ing|ant)|consulting firm|top[- ]tier consult"),
    ("Financial modeling", r"financial model(l)?ing|financial analysis|forecasting"),
    ("Statistics and experimentation", r"a/b test|experimentation|statistical|statistics"),
    ("Infrastructure as code (Terraform)", r"terraform|infrastructure as code"),
    ("Networking and security tooling (SIEM, firewalls)", r"\bsiem\b|firewalls?|\bedr\b|network security"),
    ("Healthcare or life sciences domain", r"healthcare|health care|life sciences|clinical|pharma"),
    ("Manufacturing or supply chain domain", r"manufactur|supply chain|logistics"),
    ("PMP or similar certification", r"\bpmp\b|certified scrum|\bcsm\b"),
    ("Travel to customer sites", r"travel (up to|required)|willing(ness)? to travel|\d+% travel"),
]
_CV_RX = [(n, re.compile(rx, re.I)) for n, rx in CV_SKILLS]
_OT_RX = [(n, re.compile(rx, re.I)) for n, rx in OTHER_SKILLS]
_TG_DROP = re.compile(r"\b(senior|sr\.?|staff|lead|principal|associate|junior|jr\.?|i{1,3}|iv|[1-4])\b", re.I)


def title_group(t):
    """Posting title with seniority words, team and location suffixes removed, so the same job groups together."""
    t = t or ""
    if "chief of staff" in t.lower():
        return "Chief of Staff"
    head = re.split(r"\s[-–—|]\s?|\s?\(", t)[0]
    parts = [x.strip() for x in head.split(",")]
    base = parts[0]
    if len(base.split()) <= 1 and len(parts) > 1:
        base = parts[1] + " " + parts[0]
    base = _TG_DROP.sub(" ", base)
    base = re.sub(r"[^A-Za-z&/ ]", " ", base)
    return re.sub(r"\s+", " ", base).strip().title()


def skills_in(text):
    have = [i for i, (_, rx) in enumerate(_CV_RX) if rx.search(text)]
    other = [i for i, (_, rx) in enumerate(_OT_RX) if rx.search(text)]
    return have, other


def build_dashboard(db):
    """Write dashboard.html: the template with a JSON snapshot of the figures it shows."""
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    tpl_path = os.path.join(HERE, "dashboard_template.html")
    if not os.path.exists(tpl_path):
        raise SourceError("dashboard_template.html is missing")
    mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    lab = lambda ym: "%s %s" % (mon[int(ym[5:7]) - 1], ym[:4])
    asof = q("SELECT max(last_seen) FROM job_postings")[0][0] or TODAY
    hist = q("SELECT count(DISTINCT date) FROM posting_daily")[0][0]
    roles = []
    for r in q("""SELECT company,title,location,region,lane,fit_tier,comp_min,comp_max,below_salary_floor,substr(posted_at,1,10),first_seen,url,description_text
                  FROM job_postings WHERE is_open=1 AND fit_tier IN ('target','adjacent')
                  ORDER BY CASE region WHEN 'boston_area' THEN 0 WHEN 'nyc' THEN 1 WHEN 'east_coast_other' THEN 2 WHEN 'remote' THEN 3 ELSE 4 END, fit_tier DESC, company"""):
        have, other = skills_in((r[1] or "") + " " + (r[12] or ""))
        roles.append(list(r[:12]) + [have, other, title_group(r[1])])
    # documented cases: certified H-1B filings in Massachusetts for the same job title
    cases = {}
    if _has(db, "lca"):
        groups = {}
        for r in roles:
            groups.setdefault(r[14], set()).add(r[0])
        want = {g for g, cos in groups.items() if g and len(cos) >= 2}
        acc = {}
        for emp, title, w in q("SELECT EMPLOYER_NAME, JOB_TITLE, wage_from_annualized FROM lca WHERE WORKSITE_STATE='MA' AND CASE_STATUS LIKE 'Certified%'"):
            g = title_group(title)
            if g in want:
                a = acc.setdefault(g, {"n": 0, "w": [], "e": {}})
                a["n"] += 1
                if w:
                    a["w"].append(w)
                e = (emp or "").strip()
                a["e"][e] = a["e"].get(e, 0) + 1
        cases = {g: {"n": a["n"], "wage": int(statistics.median(a["w"])) if a["w"] else None,
                     "employers": [k for k, _ in sorted(a["e"].items(), key=lambda kv: -kv[1])[:4]]} for g, a in acc.items()}
    n_bos = sum(1 for r in roles if r[3] == "boston_area")
    n_new = sum(1 for r in roles if r[10] == asof)
    co_bos = len({r[0] for r in roles if r[3] == "boston_area"})
    kpis = [
        {"value": "{:,}".format(n_bos), "label": "Open roles in your lanes, Boston area", "detail": "{:,} across all regions".format(len(roles))},
        {"value": "{:,}".format(n_new) if hist > 1 else "n/a", "label": "New roles today, your lanes",
         "detail": "all regions, first seen %s" % asof if hist > 1 else "history starts today"},
        {"value": str(co_bos), "label": "Companies hiring in your lanes, Boston", "detail": "of %s company boards tracked" % q("SELECT count(*) FROM companies WHERE last_status='ok'")[0][0]},
    ]
    unemp = [[_ym(y, p), v] for y, p, v in q("SELECT year, period, value FROM laus WHERE area_code='MT2514460000000' AND measure_code='03' AND period<>'M13' AND value IS NOT NULL ORDER BY year, period")]
    if unemp:
        prev = dict(unemp).get("%s-%s" % (int(unemp[-1][0][:4]) - 1, unemp[-1][0][5:]))
        kpis.append({"value": "%.1f%%" % unemp[-1][1], "label": "Boston metro unemployment rate",
                     "detail": lab(unemp[-1][0]) + ("; %.1f%% a year earlier" % prev if prev is not None else "")})
    jol = {}
    for y, p, e, v in q("SELECT year, period, dataelement_code, value FROM jolts WHERE state_code='25' AND seasonal='S' AND industry_code='000000' AND ratelevel_code='L' AND dataelement_code IN ('JO','HI') AND period<>'M13' AND value IS NOT NULL ORDER BY year, period"):
        jol.setdefault(_ym(y, p), {})[e] = v
    jolts = [[k, v["JO"], v["HI"]] for k, v in sorted(jol.items()) if "JO" in v and "HI" in v]
    if jolts:
        prev = {r[0]: r[1] for r in jolts}.get("%s-%s" % (int(jolts[-1][0][:4]) - 1, jolts[-1][0][5:]))
        kpis.append({"value": "%dK" % round(jolts[-1][1]), "label": "Massachusetts job openings",
                     "detail": lab(jolts[-1][0]) + ("; %dK a year earlier" % round(prev) if prev is not None else "")})
    companies = [{"company": c, "total": t, "boston": b} for c, t, b in q(
        "SELECT company, count(*), sum(region='boston_area') FROM job_postings WHERE is_open=1 AND fit_tier IN ('target','adjacent') "
        "GROUP BY company ORDER BY 3 DESC, 2 DESC LIMIT 15")]
    socs = [c.replace("-", "") for c in CFG["report_soc_codes"]]
    wd = {}
    for code, name, dtc, v in q("SELECT occupation_code, occupation_name, datatype_code, value FROM oews WHERE area_name LIKE 'Boston-Cambridge-Newton%%' AND areatype_code='M' AND occupation_code IN (%s)" % ",".join("?" * len(socs)), *socs):
        wd.setdefault(code, {"soc": code[:2] + "-" + code[2:], "name": name})[dtc] = v
    wages = [{"soc": w["soc"], "name": w["name"], "emp": w.get("01"), "p10": w.get("11"), "p25": w.get("12"), "med": w.get("13"),
              "p75": w.get("14"), "p90": w.get("15")} for w in wd.values()]
    wages.sort(key=lambda w: -(w["med"] or 0))
    ind = q("""WITH latest AS (SELECT series_id, max(year*100+CAST(substr(period,2) AS INT)) ym FROM ces
                              WHERE data_type_code='01' AND seasonal='U' AND period<>'M13' AND area_name='Boston-Cambridge-Newton, MA-NH'
                                    AND industry_code LIKE '%000000' GROUP BY series_id)
               SELECT c.industry_name, c.year, c.period, c.value, p.value FROM latest l
               JOIN ces c ON c.series_id=l.series_id AND c.year*100+CAST(substr(c.period,2) AS INT)=l.ym
               JOIN ces p ON p.series_id=c.series_id AND p.year=c.year-1 AND p.period=c.period WHERE p.value>0""")
    top_ym = max((_ym(r[1], r[2]) for r in ind), default=None)
    ind_rows = sorted(({"name": r[0], "now": r[3], "prev": r[4], "pct": round(100.0 * (r[3] - r[4]) / r[4], 1)} for r in ind if _ym(r[1], r[2]) == top_ym),
                      key=lambda d: -d["pct"])
    sponsors = []
    if _has(db, "lca"):
        kws = sorted({k for ks in CFG["lanes"].values() for k in ks})
        agg = {}
        for emp, title, w in q("SELECT EMPLOYER_NAME, JOB_TITLE, wage_from_annualized FROM lca WHERE WORKSITE_STATE='MA' AND CASE_STATUS LIKE 'Certified%'"):
            a = agg.setdefault((emp or "").upper().strip(), [emp.strip() if emp else "", 0, [], 0, []])
            a[1] += 1
            if w:
                a[2].append(w)
            if any(k in (title or "").lower() for k in kws):
                a[3] += 1
                if w:
                    a[4].append(w)
        top = sorted((a for a in agg.values() if a[3] > 0), key=lambda a: (-a[3], -a[1]))
        kpis.append({"value": "{:,}".format(len(top)), "label": "MA employers with H-1B filings for lane titles",
                     "detail": "certified filings, " + (q("SELECT min(DECISION_DATE)||' to '||max(DECISION_DATE) FROM lca")[0][0] or "")})
        sponsors = [[a[0], a[3], int(statistics.median(a[4])) if a[4] else None, a[1], int(statistics.median(a[2])) if a[2] else None] for a in top[:40]]
    sources = [[r[0], r[1], r[4], r[5], (r[6] or "")[:10], r[7]] for r in _source_rows(db)]
    data = {"asof": asof, "generated": NOW().replace("T", " "), "history_days": hist, "salary_floor": CFG["salary_floor"], "kpis": kpis,
            "roles": roles, "skills": {"have": [n for n, _ in CV_SKILLS], "other": [n for n, _ in OTHER_SKILLS]}, "cases": cases, "companies": companies, "wages": wages, "unemp": unemp, "jolts": jolts,
            "industry": {"month": lab(top_ym) if top_ym else "", "rows": ind_rows}, "sponsors": sponsors, "sources": sources, "trends": build_trends(db, asof)}
    with open(tpl_path, encoding="utf-8") as f:
        tpl = f.read()
    out = tpl.replace("__DASHBOARD_DATA__", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
    path = os.path.join(HERE, "dashboard.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    return path


def build_excel(db):
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    sheets = []
    guide = []

    def add(name, desc, headers, rows, links=()):
        sheets.append((name, headers, rows, links))
        guide.append((name, len(rows), desc))

    add("Target roles", "Open postings in your lanes that pass the level, location and restriction rules. Source: employer job boards.",
        ["Company", "Title", "Location", "Region", "Lane", "Fit tier", "Pay as posted", "Pay min", "Pay max",
         "Below salary floor (1=yes)", "Posted", "First seen", "Link"],
        q("SELECT company,title,location,region,lane,fit_tier,comp_text,comp_min,comp_max,below_salary_floor,substr(posted_at,1,10),first_seen,url FROM v_target_roles"), (12,))
    add("Company hiring", "One row per company: open roles, open roles in your lanes, Boston counts, 30-day adds and closes.",
        ["Company", "Open roles", "Open in Boston area", "Open in your lanes", "Open in your lanes, Boston", "First seen last 30d", "Closed last 30d"],
        q("SELECT * FROM v_company_hiring ORDER BY open_target_boston DESC, open_target_lane DESC, open_roles_total DESC"))
    add("All open postings", "Every open posting collected, with the tags the rules assigned.",
        ["Company", "Title", "Location", "Region", "Department", "Lane", "Fit tier", "Level flag", "Restriction flags",
         "Pay as posted", "Posted", "Link"],
        q("SELECT company,title,location,region,department,lane,fit_tier,level_flag,restriction_flags,comp_text,substr(posted_at,1,10),url FROM job_postings WHERE is_open=1 ORDER BY company,title"), (11,))
    if _has(db, "lca"):
        kws = sorted({k for ks in CFG["lanes"].values() for k in ks})
        data = q("SELECT EMPLOYER_NAME, JOB_TITLE, wage_from_annualized FROM lca WHERE WORKSITE_STATE='MA' AND CASE_STATUS LIKE 'Certified%'")
        agg = {}
        for emp, title, w in data:
            a = agg.setdefault((emp or "").upper().strip(), [emp, 0, [], 0, []])
            a[1] += 1
            if w:
                a[2].append(w)
            if any(k in (title or "").lower() for k in kws):
                a[3] += 1
                if w:
                    a[4].append(w)
        rows = [[a[0], a[1], int(statistics.median(a[2])) if a[2] else None, a[3],
                 int(statistics.median(a[4])) if a[4] else None] for a in sorted(agg.values(), key=lambda a: (-a[3], -a[1]))]
        add("H1B sponsors MA", "Employers with certified H-1B/H-1B1/E-3 filings (LCAs) for Massachusetts worksites. Source: US Department of Labor.",
            ["Employer", "Certified filings", "Median offered wage, annualized", "Filings with titles in your lanes", "Median wage, lane titles"], rows)
        like = " OR ".join("lower(JOB_TITLE) LIKE ?" for _ in kws)
        cols = "EMPLOYER_NAME,JOB_TITLE,SOC_TITLE,WORKSITE_CITY,WORKSITE_STATE,VISA_CLASS,CASE_STATUS,DECISION_DATE,WAGE_RATE_OF_PAY_FROM,WAGE_RATE_OF_PAY_TO,WAGE_UNIT_OF_PAY,wage_from_annualized,PW_WAGE_LEVEL,CASE_NUMBER"
        hdr = ["Employer", "Job title", "Occupation (SOC)", "Worksite city", "State", "Visa class", "Status", "Decision date",
               "Wage from", "Wage to", "Wage unit", "Wage from, annualized", "Prevailing wage level", "Case number"]
        num_fix = lambda rows: [[(num(v) if i in (8, 9) and num(v) is not None else v) for i, v in enumerate(r)] for r in rows]
        add("H1B filings lane titles", "Certified filings with a Massachusetts worksite whose job title matches your lane keywords.", hdr,
            num_fix(db.execute("SELECT %s FROM lca WHERE WORKSITE_STATE='MA' AND CASE_STATUS LIKE 'Certified%%' AND (%s) ORDER BY EMPLOYER_NAME" % (cols, like),
                               ["%" + k + "%" for k in kws]).fetchall()))
        add("H1B filings MA all", "Every filing with a Massachusetts worksite in the loaded files.", hdr,
            num_fix(q("SELECT %s FROM lca WHERE WORKSITE_STATE='MA' ORDER BY EMPLOYER_NAME" % cols)))
    labels = ["Employment", "Annual mean wage", "Annual 10th percentile wage", "Annual 25th percentile wage",
              "Annual median wage", "Annual 75th percentile wage", "Annual 90th percentile wage",
              "Employment per 1,000 jobs", "Location Quotient"]
    rows = _pivot(q("SELECT area_name, substr(occupation_code,1,2)||'-'||substr(occupation_code,3), occupation_name, year, datatype, value "
                    "FROM oews WHERE areatype_code='M' ORDER BY area_name, occupation_code"), 4, labels)
    add("Wages by occupation", "Employment and annual wage percentiles by occupation for Boston and other East Coast metros. Blank = not published by BLS. Source: BLS OEWS.",
        ["Metro area", "SOC code", "Occupation", "Reference year"] + labels, rows)
    rows = _pivot(q("SELECT year, period, measure, value FROM laus WHERE area_code='MT2514460000000' AND period<>'M13' ORDER BY year DESC, period DESC"),
                  2, ["labor force", "employment", "unemployment", "unemployment rate"])
    add("Boston labor force", "Monthly labor force, employment, unemployment for the Boston-Cambridge-Newton metro, not seasonally adjusted. Source: BLS LAUS.",
        ["Year", "Month", "Labor force", "Employed", "Unemployed", "Unemployment rate %"], rows)
    rows = q("""WITH latest AS (SELECT series_id, max(year*100+CAST(substr(period,2) AS INT)) ym FROM ces
                                WHERE data_type_code='01' AND seasonal='U' AND period<>'M13' AND state_code='25' GROUP BY series_id)
                SELECT c.area_name, c.industry_name, c.year, c.period, c.value, p.value, round(c.value-p.value,1),
                       round(100.0*(c.value-p.value)/p.value,1)
                FROM latest l JOIN ces c ON c.series_id=l.series_id AND c.year*100+CAST(substr(c.period,2) AS INT)=l.ym
                JOIN ces p ON p.series_id=c.series_id AND p.year=c.year-1 AND p.period=c.period
                WHERE p.value>0 ORDER BY c.area_name, 8 DESC""")
    add("MA jobs by industry", "Jobs by industry, latest month against the same month a year earlier, Massachusetts areas. Source: BLS CES.",
        ["Area", "Industry", "Year", "Month", "Jobs (thousands)", "Year earlier (thousands)", "Change (thousands)", "Change %"], rows)
    jl = ["Job openings|Level - In Thousands", "Job openings|Rate", "Hires|Level - In Thousands", "Hires|Rate",
          "Quits|Rate", "Layoffs and discharges|Rate", "Total separations|Rate", "Unemployed persons per job opening ratio|Rate"]
    rows = _pivot(q("SELECT year, period, dataelement||'|'||ratelevel, value FROM jolts WHERE state_code='25' AND seasonal='S' "
                    "AND industry_code='000000' AND period<>'M13' ORDER BY year DESC, period DESC"), 2, jl)
    add("MA openings and hires", "Massachusetts job openings, hires, quits and layoffs, seasonally adjusted. Source: BLS JOLTS.",
        ["Year", "Month", "Job openings (thousands)", "Job openings rate", "Hires (thousands)", "Hires rate", "Quits rate",
         "Layoffs rate", "Total separations rate", "Unemployed per job opening"], rows)
    if _has(db, "qcew") and _has(db, "qcew_industry_titles") and "oty_avg_wkly_wage_pct_chg" in [r[1] for r in db.execute("PRAGMA table_info(qcew)")]:
        rows = q("""SELECT q.year, q.qtr, t.title, q.qtrly_estabs, q.month3_emplvl, q.avg_wkly_wage, q.oty_month3_emplvl_pct_chg, q.oty_avg_wkly_wage_pct_chg
                    FROM qcew q LEFT JOIN qcew_industry_titles t ON t.code=q.industry_code
                    WHERE q.area_fips='C1446' AND q.own_code='5' AND q.agglvl_code IN ('44','45')
                    ORDER BY q.year DESC, q.qtr DESC, CAST(q.month3_emplvl AS INT) DESC""")
        rows = [[num(v) if i != 2 and num(v) is not None else v for i, v in enumerate(r)] for r in rows]
        rows = [r for r in rows if isinstance(r[4], float) and r[4] > 0]  # drop rows BLS suppressed for confidentiality
        rows.sort(key=lambda r: (-r[0], -r[1], -r[4]))
        add("Boston industries", "Private-sector establishments, employment, average weekly wage and year-over-year change by industry, Boston metro, per quarter. Source: BLS QCEW.",
            ["Year", "Quarter", "Industry", "Establishments", "Employment (3rd month)", "Avg weekly wage", "Employment change % vs year ago", "Wage change % vs year ago"], rows)
    add("Source status", "What loaded and what failed on the latest run of each source.",
        ["Source", "Publisher", "Description", "Last status", "Last run", "Rows", "Detail", "URL"],
        q("""SELECT s.source, s.publisher, s.description,
                    (SELECT status FROM source_status x WHERE x.source=s.source ORDER BY run_at DESC LIMIT 1),
                    (SELECT run_at FROM source_status x WHERE x.source=s.source ORDER BY run_at DESC LIMIT 1),
                    (SELECT rows FROM source_status x WHERE x.source=s.source ORDER BY run_at DESC LIMIT 1),
                    (SELECT detail FROM source_status x WHERE x.source=s.source ORDER BY run_at DESC LIMIT 1), s.url FROM sources s"""))
    src_rows = _source_rows(db)
    companies = q("SELECT count(*), sum(last_status='ok') FROM companies")[0]
    src_rows.append(["Employer job boards: company list", "The %s company boards queried for live postings (%s answered on the last run). Full list in exports/companies.csv"
                     % (companies[0], companies[1] or 0), "exports/companies.csv", "Target roles; Company hiring; All open postings", "", companies[0], "", "", "every day", "companies"])
    sheets.insert(0, ("Sources", ["Publisher", "What it contains", "Where it comes from (URL)", "Sheets that use it", "Period covered",
                                   "Rows in database", "Last successful load", "Latest run status", "Refresh check", "Database table / CSV name"], src_rows, ()))
    guide.insert(0, ("Sources", len(src_rows), "Every data source: publisher, URL, period covered, rows loaded, last refresh, and which sheets use it."))
    guide_rows = [["Generated " + NOW() + ". Public sources only; no estimated or filled-in rows.", None, None]] + [list(g) for g in guide] + \
                 [["Full raw tables (over 1 million rows) are in the exports folder as CSV files.", None, None]]
    sheets.insert(0, ("Guide", ["Sheet", "Rows", "What it holds"], guide_rows, ()))
    path = os.path.join(HERE, "jobmarket.xlsx")
    write_xlsx(path, sheets)
    return path, guide


def print_status(db):
    print("\nSource status (latest run per source):")
    for s, in db.execute("SELECT source FROM sources"):
        r = db.execute("SELECT status, run_at, rows, detail FROM source_status WHERE source=? ORDER BY run_at DESC LIMIT 1", (s,)).fetchone()
        print("  %-9s %s" % (s, "never run" if not r else "%s  %s  rows=%s  %s" % (r[0].upper(), r[1], r[2], (r[3] or "")[:110])))
    print("\nRow counts:")
    for t, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        print("  %-22s %s" % (t, db.execute('SELECT count(*) FROM "%s"' % t).fetchone()[0]))


RUNNERS = [("laus", src_laus), ("ces", src_ces), ("jolts", src_jolts), ("oews", src_oews), ("qcew", src_qcew),
           ("acs", src_acs), ("qwi", src_qwi), ("cbp", src_cbp), ("lca", src_lca), ("discover", src_discover),
           ("jobs", src_jobs)]


def cmd_update(db, only, force):
    print("Update started %s" % NOW())
    for name, fn in RUNNERS:
        if only and name not in only:
            continue
        if not is_due(db, name, force or bool(only)):
            print("  [skip] %s: refreshed within its interval" % name)
            continue
        try:
            rows, detail = fn(db)
            db.commit()
            record(db, name, "ok", rows, detail)
        except SourceError as e:
            db.rollback()
            record(db, name, "failed", 0, str(e))
        except Exception as e:  # never let one source stop the others
            db.rollback()
            record(db, name, "failed", 0, "%s: %s" % (type(e).__name__, e))
    outdir, written = export_all(db)
    path = build_report(db)
    print("Exports: %s (%s files). Report: %s" % (outdir, len(written), path))
    try:
        print("Excel workbook: %s" % build_excel(db)[0])
    except Exception as e:
        print("Excel workbook not written: %s: %s" % (type(e).__name__, e))
    try:
        print("Dashboard page: %s" % build_dashboard(db))
    except Exception as e:
        print("Dashboard page not written: %s: %s" % (type(e).__name__, e))
    print_status(db)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["update", "discover", "export", "report", "status", "excel", "dashboard"])
    ap.add_argument("--only", default="", help="comma separated source names")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--db", default=os.path.join(HERE, "jobmarket.db"))
    ap.add_argument("--out", default=None, help="export directory")
    a = ap.parse_args()
    db = open_db(a.db)
    if a.command == "update":
        cmd_update(db, set(x for x in a.only.split(",") if x), a.force)
    elif a.command == "discover":
        cmd_update(db, {"discover", "jobs"}, True)
    elif a.command == "export":
        outdir, written = export_all(db, a.out)
        for t, n in written:
            print("  %-22s %s rows" % (t, n))
        print("Written to", outdir)
    elif a.command == "report":
        print("Written", build_report(db))
    elif a.command == "status":
        print_status(db)
    elif a.command == "dashboard":
        print("Written", build_dashboard(db))
    elif a.command == "excel":
        path, guide = build_excel(db)
        for name, n, _ in guide:
            print("  %-26s %s rows" % (name, n))
        print("Written", path)


if __name__ == "__main__":
    main()
