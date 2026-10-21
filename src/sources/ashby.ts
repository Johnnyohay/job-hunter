import type { Job } from "../types.ts";

interface AshbyJob {
  id: string;
  title: string;
  location?: string;
  secondaryLocations?: { location?: string }[];
  isRemote?: boolean;
  workplaceType?: string;
  jobUrl: string;
  applyUrl: string;
  descriptionPlain?: string;
  publishedAt?: string;
  compensation?: { compensationTierSummary?: string | null; scrapeableCompensationSalarySummary?: string | null };
}

function toJob(board: string, company: string, j: AshbyJob): Job {
  const locations = [j.location, ...(j.secondaryLocations ?? []).map((l) => l.location)].filter(Boolean);
  return {
    id: `ashby:${board}:${j.id}`,
    ats: "ashby",
    board,
    company: company || board,
    title: j.title,
    location: locations.join(" / "),
    workplace: j.isRemote ? "Remote" : (j.workplaceType ?? ""),
    compensation:
      j.compensation?.compensationTierSummary ?? j.compensation?.scrapeableCompensationSalarySummary ?? "",
    url: j.jobUrl,
    applyUrl: j.applyUrl,
    description: j.descriptionPlain ?? "",
    postedAt: j.publishedAt,
  };
}

export async function fetchAshby(board: string, company: string): Promise<Job[]> {
  const res = await fetch(`https://api.ashbyhq.com/posting-api/job-board/${board}?includeCompensation=true`);
  if (!res.ok) throw new Error(`Ashby ${board}: HTTP ${res.status}`);
  return ((await res.json()) as { jobs: AshbyJob[] }).jobs.map((j) => toJob(board, company, j));
}

export async function fetchAshbyJob(board: string, id: string): Promise<Job> {
  const job = (await fetchAshby(board, "")).find((j) => j.id === `ashby:${board}:${id}`);
  if (!job) throw new Error(`Ashby ${board}/${id}: not found (closed?)`);
  return job;
}
