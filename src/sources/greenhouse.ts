import { htmlToText } from "../text.ts";
import type { Job } from "../types.ts";

interface GhJob {
  id: number;
  title: string;
  absolute_url: string;
  location?: { name?: string };
  content?: string;
  company_name?: string;
  first_published?: string;
  updated_at?: string;
}

function toJob(board: string, company: string, j: GhJob): Job {
  const location = j.location?.name ?? "";
  return {
    id: `greenhouse:${board}:${j.id}`,
    ats: "greenhouse",
    board,
    company: company || j.company_name || board,
    title: j.title,
    location,
    workplace: /remote/i.test(location) ? "Remote" : "",
    compensation: "",
    url: j.absolute_url,
    applyUrl: `https://job-boards.greenhouse.io/${board}/jobs/${j.id}`,
    description: htmlToText(j.content ?? ""),
    postedAt: j.first_published ?? j.updated_at,
  };
}

export async function fetchGreenhouse(board: string, company: string): Promise<Job[]> {
  const res = await fetch(`https://boards-api.greenhouse.io/v1/boards/${board}/jobs?content=true`);
  if (!res.ok) throw new Error(`Greenhouse ${board}: HTTP ${res.status}`);
  const data = (await res.json()) as { jobs: GhJob[] };
  return data.jobs.map((j) => toJob(board, company, j));
}

export async function fetchGreenhouseJob(board: string, id: string): Promise<Job> {
  const res = await fetch(`https://boards-api.greenhouse.io/v1/boards/${board}/jobs/${id}`);
  if (!res.ok) throw new Error(`Greenhouse ${board}/${id}: HTTP ${res.status}`);
  return toJob(board, "", (await res.json()) as GhJob);
}
