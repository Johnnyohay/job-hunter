import { htmlToText } from "../text.ts";
import type { Company, Job } from "../types.ts";
import { fetchAshby, fetchAshbyJob } from "./ashby.ts";
import { fetchGreenhouse, fetchGreenhouseJob } from "./greenhouse.ts";
import { fetchLever, fetchLeverJob } from "./lever.ts";

export function fetchBoard(c: Company): Promise<Job[]> {
  switch (c.ats) {
    case "greenhouse":
      return fetchGreenhouse(c.board, c.company);
    case "lever":
      return fetchLever(c.board, c.company);
    case "ashby":
      return fetchAshby(c.board, c.company);
    default:
      return Promise.reject(new Error(`${c.company}: unsupported ATS "${c.ats}" (use greenhouse, lever or ashby)`));
  }
}

/** Turns a job URL pasted into "Target Positions" into a Job, using the ATS API when the URL is recognized. */
export async function fetchJobUrl(url: string, company: string, title: string): Promise<Job> {
  let m = url.match(/greenhouse\.io\/(?:embed\/job_app\?for=)?([\w-]+)\/jobs\/(\d+)/) ?? url.match(/[?&]for=([\w-]+).*[?&]token=(\d+)/);
  if (m) return withOverrides(await fetchGreenhouseJob(m[1], m[2]), company, title);
  m = url.match(/jobs\.lever\.co\/([\w-]+)\/([\w-]{36})/);
  if (m) return withOverrides(await fetchLeverJob(m[1], m[2]), company, title);
  m = url.match(/jobs\.ashbyhq\.com\/([\w.-]+)\/([\w-]{36})/);
  if (m) return withOverrides(await fetchAshbyJob(m[1], m[2]), company, title);

  // Any other site (Workday, company pages...): keep the page text; the apply step stays manual.
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

function withOverrides(job: Job, company: string, title: string): Job {
  return { ...job, company: company || job.company, title: title || job.title };
}
