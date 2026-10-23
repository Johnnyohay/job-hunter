// Final step of the daily run: turns Claude Code's verdicts (.state/results.json) and drafted materials
// (.state/materials/*.md) into tracker rows and Google Docs. Usage: npm run record
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { z } from "zod";
import { STATE } from "./env.ts";
import type { RunInfo } from "./fetch.ts";
import { createDoc } from "./google.ts";
import { STATUS, appendRows, readTracker, type Row } from "./tracker.ts";
import type { Job } from "./types.ts";

const Result = z.object({
  id: z.string(),
  fit: z.number().min(0).max(100),
  recommendation: z.enum(["apply", "maybe", "skip"]),
  why_it_fits: z.string(),
  gaps: z.string().default(""),
  deal_breakers: z.array(z.string()).default([]),
  hiring_manager: z.object({
    name: z.string(),
    title: z.string(),
    linkedin_url: z.string(),
    confidence: z.enum(["high", "medium", "low", "none"]),
    evidence: z.string().default(""),
  }).nullish(),
  materials_file: z.string().nullish(),
  needs_from_you: z.array(z.string()).default([]),
});

const read = <T>(file: string): T => JSON.parse(readFileSync(`${STATE}/${file}`, "utf8"));

async function main() {
  if (!existsSync(`${STATE}/results.json`)) throw new Error(`No ${STATE}/results.json: nothing to record.`);
  const run = read<RunInfo>("run.json");
  const jobs = new Map(read<Job[]>("candidates.json").map((j) => [j.id, j]));
  const results = z.array(Result).parse(read<unknown>("results.json"));
  const tracked = new Set((await readTracker(run.trackerId)).map((r) => r["Job ID"]));
  const problems: string[] = [];

  const rows: Row[] = [];
  for (const r of results) {
    const job = jobs.get(r.id);
    if (!job) {
      problems.push(`results.json has an id that is not in candidates.json: ${r.id}`);
      continue;
    }
    if (tracked.has(job.id)) continue; // already recorded by an earlier run
    const shortlisted = r.fit >= run.minFit && r.recommendation !== "skip";
    const row: Row = {
      "Job ID": job.id, Found: run.date, Company: job.company, Title: job.title, Location: job.location,
      Workplace: job.workplace, Compensation: job.compensation, Fit: String(r.fit),
      Status: shortlisted ? STATUS.shortlisted : STATUS.notAFit,
      "Why it fits": r.why_it_fits,
      "Gaps / risks": [r.gaps, ...r.deal_breakers.map((d) => `Deal-breaker: ${d}`)].filter(Boolean).join(" "),
      "Job URL": job.url, "Apply URL": job.applyUrl, "Last Update": run.date,
    };
    const hm = r.hiring_manager;
    if (hm && hm.confidence !== "none" && hm.name) {
      row["Hiring Manager"] = `${hm.name}, ${hm.title} (${hm.confidence})`;
      // Only real profile links; never a constructed or search-page URL.
      if (/^https:\/\/([a-z]{2,3}\.)?linkedin\.com\/in\/[^/?#\s]+\/?$/i.test(hm.linkedin_url)) row["HM LinkedIn"] = hm.linkedin_url;
    }
    if (r.materials_file) {
      try {
        const text = readFileSync(r.materials_file, "utf8");
        row.Materials = await createDoc(run.applicationsFolderId, `${job.company} - ${job.title}`, text);
        row.Status = STATUS.ready;
      } catch (e) {
        problems.push(`materials for ${job.company} ${job.title}: ${(e as Error).message}`);
      }
    }
    if (r.needs_from_you.length) row.Notes = `Needs from you: ${r.needs_from_you.join("; ")}`;
    rows.push(row);
  }

  rows.sort((a, b) => Number(b.Fit ?? 0) - Number(a.Fit ?? 0));
  await appendRows(run.trackerId, rows);
  // Keep the run's files but stop a second `npm run record` from recording them again.
  renameSync(`${STATE}/results.json`, `${STATE}/results.recorded.json`);

  const ready = rows.filter((r) => r.Status === STATUS.ready);
  const shortlisted = rows.filter((r) => r.Status !== STATUS.notAFit);
  const fetchProblems = existsSync(`${STATE}/fetch-problems.txt`) ? readFileSync(`${STATE}/fetch-problems.txt`, "utf8").split("\n") : [];
  const allProblems = [...fetchProblems, ...problems].filter(Boolean);
  const summary = [
    `## Job agent: ${run.date}`,
    `${rows.length} new jobs scored, ${shortlisted.length} shortlisted (fit >= ${run.minFit}), ${ready.length} prepared for review.`,
    ...ready.map((r) => `- **${r.Company}**: ${r.Title} (fit ${r.Fit}): ${r.Materials}`),
    ...(allProblems.length ? ["", "### Problems", ...allProblems.map((e) => `- ${e}`)] : []),
  ].join("\n");
  console.log(summary);
  writeFileSync(`${STATE}/summary.md`, summary + "\n");
  mkdirSync("logs", { recursive: true });
  appendFileSync("logs/history.md", summary + "\n\n");
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
});
