// Step 1 of the daily run: pulls my profile from Drive and the new jobs to evaluate into .state/.
// Claude Code then scores them (see .claude/commands/daily.md) and `npm run record` writes the results back.
// Usage: npm run fetch [-- --dry-run]
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { STATE } from "./env.ts";
import { passesPrefilter, search } from "./filter.ts";
import { loadCompanies, loadProfile, loadTargets } from "./profile.ts";
import { fetchBoard, fetchJobUrl } from "./sources/index.ts";
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

async function main() {
  const profile = await loadProfile();
  const tracked = new Set((await readTracker(profile.trackerId)).map((r) => r["Job ID"]));

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
  const fresh = (j: Job) => !tracked.has(j.id);
  const candidates = [
    ...targetJobs.filter(fresh),
    ...boardJobs.filter(fresh).filter((j) => passesPrefilter(j))
      .sort((a, b) => (b.postedAt ?? "").localeCompare(a.postedAt ?? "")),
  ].slice(0, search.limits.maxScoredPerRun);

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
    candidates.map((j) => ({ ...j, description: j.description.slice(0, 6000) })),
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
