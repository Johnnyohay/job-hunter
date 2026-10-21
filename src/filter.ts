import { readFileSync } from "node:fs";
import { parse } from "yaml";
import type { Job } from "./types.ts";

export interface SearchConfig {
  include: string[];
  exclude: string[];
  locations: string[];
  limits: { maxScoredPerRun: number; maxTailoredPerRun: number; minFit: number };
}

export const search = parse(readFileSync("config/search.yaml", "utf8")) as SearchConfig;

const words = (s: string) => ` ${s.toLowerCase().replace(/[^a-z0-9]+/g, " ")} `;
const has = (text: string, term: string) => words(text).includes(words(term));

/** Cheap title/location screen so only plausible jobs reach Claude. */
export function passesPrefilter(job: Job, cfg: SearchConfig = search): boolean {
  if (!cfg.include.some((t) => has(job.title, t))) return false;
  if (cfg.exclude.some((t) => has(job.title, t))) return false;
  if (!cfg.locations.length) return true;
  const where = `${job.location} ${job.workplace}`;
  return !job.location || cfg.locations.some((l) => has(where, l));
}
