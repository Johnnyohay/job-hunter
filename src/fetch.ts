// Step 1 of the daily run: pulls my profile from Drive and the new jobs to evaluate into .state/.
// Claude Code then scores them (see .claude/commands/daily.md) and `npm run record` writes the results back.
// Usage: npm run fetch [-- --dry-run]
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { STATE } from "./env.ts";
import { passesPrefilter, search } from "./filter.ts";
import { loadCompanies, loadProfile, loadTargets } from "./profile.ts";
import { fetchBoard, fetchJobUrl } from "./sources.ts";
import { readTracker, today } from "./tracker.ts";
import type { Job } from "./types.ts";

export interface RunInfo {
  date: string;
  minFit: number;
  maxTailored: number;
  trackerId: string;
  applicationsFolderId: string;
}

const dryRun = process.argv.includes("--dry-run");

/** Same company + same title (ignoring case, punctuation and bracketed notes like "(Remote)") = same position. */
export const roleKey = (company: string, title: string) =>
  `${company} | ${title.replace(/\([^)]*\)|\[[^\]]*\]/g, " ")}`.toLowerCase().replace(/[^a-z0-9|]+/g, " ").trim();

async function main() {
  const profile = await loadProfile();
  const rows = await readTracker(profile.trackerId);
  const tracked = new Set(rows.map((r) => r["Job ID"]));
  const trackedRoles = new Set(rows.filter((r) => r.Company && r.Title).map((r) => roleKey(r.Company!, r.Title!)));

  // Collect: every watched company's board, plus the specific positions I listed.
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

  // Screen: new jobs only; listed positions skip the keyword filter.
  // A position counts once: the same company + title reposted on another day, or posted once per city,
  // is noise. Reposts of a tracked role are dropped; same-role postings in one run merge their locations.
  const fresh = (j: Job) => !tracked.has(j.id) && !trackedRoles.has(roleKey(j.company, j.title));
  const byRole = new Map<string, Job>();
  for (const j of [
    ...targetJobs.filter(fresh),
    ...boardJobs.filter(fresh).filter((j) => passesPrefilter(j))
      .sort((a, b) => (b.postedAt ?? "").localeCompare(a.postedAt ?? "")),
  ]) {
    const k = roleKey(j.company, j.title);
    const kept = byRole.get(k);
    if (!kept) byRole.set(k, { ...j });
    else if (j.location && !kept.location.includes(j.location)) kept.location = [kept.location, j.location].filter(Boolean).join(" / ");
  }
  const candidates = [...byRole.values()].slice(0, search.limits.maxScoredPerRun);

  console.log(`${companies.length} companies, ${boardJobs.length} open jobs, ${targetJobs.length} listed positions -> ${candidates.length} new to score`);
  for (const e of errors) console.log(`  problem: ${e}`);
  if (dryRun) {
    for (const j of candidates) console.log(`  would score: ${j.company} | ${j.title} | ${j.location}`);
    return;
  }

  rmSync(STATE, { recursive: true, force: true });
  mkdirSync(`${STATE}/profile`, { recursive: true });
  mkdirSync(`${STATE}/materials`, { recursive: true });
  if (profile.cvPdf) writeFileSync(`${STATE}/profile/CV.pdf`, profile.cvPdf);
  if (profile.cvText) writeFileSync(`${STATE}/profile/CV.txt`, profile.cvText);
  if (profile.linkedinPdf) writeFileSync(`${STATE}/profile/LinkedIn.pdf`, profile.linkedinPdf);
  writeFileSync(`${STATE}/profile/about-me.txt`, profile.aboutMe || "(empty)");
  writeFileSync(`${STATE}/profile/job-preferences.txt`, profile.preferences);

  const run: RunInfo = {
    date: today(),
    minFit: profile.minFit ?? search.limits.minFit,
    maxTailored: profile.maxPerDay ?? search.limits.maxTailoredPerRun,
    trackerId: profile.trackerId,
    applicationsFolderId: profile.applicationsFolderId,
  };
  writeFileSync(`${STATE}/run.json`, JSON.stringify(run, null, 2));
  writeFileSync(`${STATE}/candidates.json`, JSON.stringify(
    candidates.map((j) => ({ ...j, description: j.description.slice(0, 15000) })),
    null,
    2,
  ));
  if (errors.length) writeFileSync(`${STATE}/fetch-problems.txt`, errors.join("\n"));
  console.log(`Wrote ${STATE}/candidates.json and ${STATE}/profile/. Minimum fit ${run.minFit}, up to ${run.maxTailored} to prepare.`);
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
});
