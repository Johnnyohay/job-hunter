import { search } from "../config/search.ts";
import type { Job } from "./types.ts";

export { search };

const words = (s: string) => ` ${s.toLowerCase().replace(/[^a-z0-9]+/g, " ")} `;
const has = (text: string, term: string) => words(text).includes(words(term));

/** Cheap title/location screen so only plausible jobs reach Claude. */
export function passesPrefilter(job: Job, cfg = search): boolean {
  if (!cfg.include.some((t) => has(job.title, t))) return false;
  if (cfg.exclude.some((t) => has(job.title, t))) return false;
  if (!cfg.locations.length) return true;
  const where = `${job.location} ${job.workplace}`;
  return !job.location || cfg.locations.some((l) => has(where, l));
}
