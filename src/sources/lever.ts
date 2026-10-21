import type { Job } from "../types.ts";

interface LeverJob {
  id: string;
  text: string;
  hostedUrl: string;
  applyUrl: string;
  categories?: { location?: string; team?: string; commitment?: string; allLocations?: string[] };
  workplaceType?: string;
  descriptionPlain?: string;
  additionalPlain?: string;
  lists?: { text: string; content: string }[];
  salaryRange?: { min?: number; max?: number; currency?: string; interval?: string };
  createdAt?: number;
}

function toJob(board: string, company: string, j: LeverJob): Job {
  const lists = (j.lists ?? []).map((l) => `${l.text}\n${l.content.replace(/<[^>]+>/g, " ")}`).join("\n\n");
  const s = j.salaryRange;
  return {
    id: `lever:${board}:${j.id}`,
    ats: "lever",
    board,
    company: company || board,
    title: j.text,
    location: j.categories?.allLocations?.join(" / ") || j.categories?.location || "",
    workplace: j.workplaceType ?? "",
    compensation: s?.min ? `${s.currency ?? ""} ${s.min}-${s.max ?? ""} ${s.interval ?? ""}`.trim() : "",
    url: j.hostedUrl,
    applyUrl: j.applyUrl,
    description: [j.descriptionPlain, lists, j.additionalPlain].filter(Boolean).join("\n\n"),
    postedAt: j.createdAt ? new Date(j.createdAt).toISOString() : undefined,
  };
}

export async function fetchLever(board: string, company: string): Promise<Job[]> {
  const res = await fetch(`https://api.lever.co/v0/postings/${board}?mode=json`);
  if (!res.ok) throw new Error(`Lever ${board}: HTTP ${res.status}`);
  return ((await res.json()) as LeverJob[]).map((j) => toJob(board, company, j));
}

export async function fetchLeverJob(board: string, id: string): Promise<Job> {
  const res = await fetch(`https://api.lever.co/v0/postings/${board}/${id}`);
  if (!res.ok) throw new Error(`Lever ${board}/${id}: HTTP ${res.status}`);
  return toJob(board, "", (await res.json()) as LeverJob);
}
