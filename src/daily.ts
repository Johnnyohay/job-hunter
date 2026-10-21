import { appendFileSync } from "node:fs";
import { draftMaterials, findHiringManager, profileBlocks, scoreJob, type FitResult } from "./claude.ts";
import { passesPrefilter, search } from "./filter.ts";
import { createDoc } from "./google.ts";
import { materialsDoc } from "./materials.ts";
import { loadCompanies, loadProfile, loadTargets } from "./profile.ts";
import { fetchBoard, fetchJobUrl } from "./sources/index.ts";
import { STATUS, appendRows, readTracker, today, type Row } from "./tracker.ts";
import type { Job } from "./types.ts";

const dryRun = process.argv.includes("--dry-run");
const log = (...a: unknown[]) => console.log(new Date().toISOString().slice(11, 19), ...a);

async function mapLimit<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const i = next++;
      out[i] = await fn(items[i]);
    }
  }));
  return out;
}

async function main() {
  const profile = await loadProfile();
  const tracked = new Set((await readTracker(profile.trackerId)).map((r) => r["Job ID"]));
  const minFit = profile.minFit ?? search.limits.minFit;
  const maxTailored = profile.maxPerDay ?? search.limits.maxTailoredPerRun;

  // 1. Collect: every watched company's board, plus the specific positions you listed.
  const companies = await loadCompanies(profile);
  const boards = await Promise.allSettled(companies.map(fetchBoard));
  const errors: string[] = [];
  const boardJobs = boards.flatMap((b, i) => {
    if (b.status === "fulfilled") return b.value;
    errors.push(`${companies[i].company}: ${b.reason}`);
    return [];
  });
  const targets = await Promise.allSettled(
    (await loadTargets(profile)).filter((t) => !tracked.has(`manual:${t.url}`)).map((t) => fetchJobUrl(t.url, t.company, t.title)),
  );
  const targetJobs = targets.flatMap((t) => (t.status === "fulfilled" ? [t.value] : (errors.push(String(t.reason)), [])));

  // 2. Screen: new jobs only; listed positions skip the keyword filter.
  const fresh = (j: Job) => !tracked.has(j.id);
  const candidates = [
    ...targetJobs.filter(fresh),
    ...boardJobs.filter(fresh).filter((j) => passesPrefilter(j))
      .sort((a, b) => (b.postedAt ?? "").localeCompare(a.postedAt ?? "")),
  ].slice(0, search.limits.maxScoredPerRun);
  log(`${companies.length} companies, ${boardJobs.length} open jobs, ${targetJobs.length} listed positions -> ${candidates.length} new to score`);
  if (dryRun) {
    for (const j of candidates) log(`  would score: ${j.company} | ${j.title} | ${j.location}`);
    return;
  }

  // 3. Score each candidate against the CV and preferences.
  const blocks = profileBlocks(profile);
  const scored = await mapLimit(candidates, 4, async (job) => {
    try {
      return { job, fit: await scoreJob(blocks, job) };
    } catch (e) {
      errors.push(`score ${job.company} ${job.title}: ${(e as Error).message}`);
      return { job, fit: null as FitResult | null };
    }
  });

  // 4. For the best matches: find the hiring manager and draft materials into Drive.
  const shortlist = scored
    .filter((s) => s.fit && s.fit.fit >= minFit && s.fit.recommendation !== "skip")
    .sort((a, b) => b.fit!.fit - a.fit!.fit);
  const toTailor = new Set(shortlist.slice(0, maxTailored).map((s) => s.job.id));

  const rows: Row[] = await mapLimit(scored, 2, async ({ job, fit }) => {
    const row: Row = {
      "Job ID": job.id, Found: today(), Company: job.company, Title: job.title, Location: job.location,
      Workplace: job.workplace, Compensation: job.compensation, "Job URL": job.url, "Apply URL": job.applyUrl,
      "Last Update": today(),
    };
    if (!fit) return { ...row, Status: STATUS.notAFit, Notes: "Could not score; check the run log." };
    Object.assign(row, {
      Fit: String(fit.fit),
      "Why it fits": fit.why_it_fits,
      "Gaps / risks": [fit.gaps, ...fit.deal_breakers.map((d) => `Deal-breaker: ${d}`)].filter(Boolean).join(" "),
      Status: shortlist.some((s) => s.job.id === job.id) ? STATUS.shortlisted : STATUS.notAFit,
    });
    if (!toTailor.has(job.id)) return row;
    try {
      const hm = await findHiringManager(job).catch(() => null);
      if (hm && hm.confidence !== "none") {
        row["Hiring Manager"] = `${hm.name}, ${hm.title} (${hm.confidence})`;
        row["HM LinkedIn"] = hm.linkedin_url;
      }
      const m = await draftMaterials(blocks, job);
      if (m) {
        row.Materials = await createDoc(profile.applicationsFolderId, `${job.company} - ${job.title}`, materialsDoc(job, m, hm));
        row.Status = STATUS.ready;
        if (m.needs_from_candidate.length) row.Notes = `Needs from you: ${m.needs_from_candidate.join("; ")}`;
      }
    } catch (e) {
      errors.push(`tailor ${job.company} ${job.title}: ${(e as Error).message}`);
    }
    return row;
  });

  await appendRows(profile.trackerId, rows.sort((a, b) => Number(b.Fit ?? 0) - Number(a.Fit ?? 0)));

  const ready = rows.filter((r) => r.Status === STATUS.ready);
  const summary = [
    `## Job agent: ${today()}`,
    `${candidates.length} new jobs scored, ${shortlist.length} shortlisted (fit >= ${minFit}), ${ready.length} drafted for review.`,
    ...ready.map((r) => `- **${r.Company}**: ${r.Title} (fit ${r.Fit}) - [materials](${r.Materials})`),
    ...(errors.length ? ["", "### Problems", ...errors.map((e) => `- ${e}`)] : []),
  ].join("\n");
  console.log(summary);
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary + "\n");
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
});
