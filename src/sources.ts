// Reads job boards using the descriptions in config/ats.ts. This file knows no ATS by name.
import { ATS, type AtsConfig } from "../config/ats.ts";
import { htmlToText } from "./text.ts";
import type { Company, Job } from "./types.ts";

/** Every value at a path like "a.b", "list[].c" or "list[]". */
function pick(obj: unknown, path: string): unknown[] {
  let values: unknown[] = [obj];
  for (const key of path.split(".")) {
    const each = key.endsWith("[]");
    const name = each ? key.slice(0, -2) : key;
    values = values.flatMap((v) => {
      const next = v != null && typeof v === "object" ? (v as Record<string, unknown>)[name] : undefined;
      return each && Array.isArray(next) ? next : [next];
    });
  }
  return values.filter((v) => v != null && v !== "");
}

const text = (obj: unknown, paths: string[] = [], sep = "\n\n") =>
  [...new Set(paths.flatMap((p) => pick(obj, p)).map((v) => htmlToText(String(v))))].join(sep);

function toJob(ats: string, cfg: AtsConfig, board: string, company: string, raw: unknown): Job {
  const f = cfg.fields;
  const one = (path: string) => pick(raw, path)[0];
  const id = one(f.id);
  const title = one(f.title);
  const url = one(f.url);
  const missing = Object.entries({ id, title, url }).filter(([, v]) => v == null).map(([k]) => k);
  if (missing.length) throw new Error(`${ats} response no longer has ${missing.join(", ")} where config/ats.ts expects it`);

  const fill = (template: string) =>
    template.replace("{url}", String(url).replace(/\/$/, "")).replace("{board}", board).replace("{id}", String(id));
  const applyUrl = !f.applyUrl ? String(url) : f.applyUrl.includes("{") ? fill(f.applyUrl) : String(one(f.applyUrl) ?? url);
  const posted = f.posted ? one(f.posted) : undefined;

  return {
    id: `${ats}:${board}:${id}`,
    ats,
    board,
    company,
    title: String(title).trim(),
    location: text(raw, f.location, " / "),
    workplace: text(raw, f.workplace, " "),
    compensation: text(raw, f.pay, " "),
    url: String(url),
    applyUrl,
    description: text(raw, f.description),
    postedAt: posted == null ? undefined : new Date(posted as string | number).toISOString(),
  };
}

export async function fetchBoard(c: Company): Promise<Job[]> {
  const cfg = ATS[c.ats];
  if (!cfg) throw new Error(`unknown ATS "${c.ats}" (known: ${Object.keys(ATS).join(", ")}; add others in config/ats.ts)`);
  const res = await fetch(cfg.list.replace("{board}", encodeURIComponent(c.board)));
  if (!res.ok) throw new Error(`${c.ats} board "${c.board}": HTTP ${res.status}`);
  const body = await res.json();
  const jobs = cfg.jobs ? pick(body, cfg.jobs)[0] : body;
  if (!Array.isArray(jobs)) throw new Error(`${c.ats} response has no job list at "${cfg.jobs}" (config/ats.ts)`);
  return jobs.map((j) => toJob(c.ats, cfg, c.board, c.company || c.board, j));
}

/** The ATS, board and job id behind a posting URL, when it's on a known board. */
export function parsePostingUrl(url: string): { ats: string; board: string; id: string } | undefined {
  for (const [ats, cfg] of Object.entries(ATS)) {
    const m = url.match(cfg.postingUrl);
    if (m) return { ats, board: m[1], id: m[2] };
  }
  return undefined;
}

const boards = new Map<string, Promise<Job[]>>();

/** Re-reads one posting from its tracker id ("greenhouse:board:123"); undefined once it's closed. */
export async function fetchJobById(jobId: string, company = ""): Promise<Job | undefined> {
  const [ats, board] = jobId.split(":");
  if (!ATS[ats]) return undefined;
  const key = `${ats}:${board}`;
  if (!boards.has(key)) boards.set(key, fetchBoard({ ats, board, company: company || board }));
  return (await boards.get(key)!).find((j) => j.id === jobId);
}

/** A URL pasted into "Target Positions": read from its board when known, otherwise from the page text. */
export async function fetchJobUrl(url: string, company: string, title: string): Promise<Job> {
  const known = parsePostingUrl(url);
  if (known) {
    const job = await fetchJobById(`${known.ats}:${known.board}:${known.id}`, company);
    if (!job) throw new Error(`${url}: not on the ${known.ats} board anymore (closed?)`);
    return { ...job, title: title || job.title };
  }
  // Any other site (Workday, company pages...): keep the page text; Claude reads it, applying stays manual.
  const res = await fetch(url, { headers: { "user-agent": "Mozilla/5.0 job-agent" } });
  const page = res.ok ? htmlToText(await res.text()) : "";
  return {
    id: `manual:${url}`,
    ats: "manual",
    board: "",
    company: company || new URL(url).hostname,
    title: title || "(see posting)",
    location: "",
    workplace: "",
    compensation: "",
    url,
    applyUrl: url,
    description: page.slice(0, 20000) || "(Could not load the page; judge from the title and company.)",
  };
}
