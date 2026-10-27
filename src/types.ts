/** A posting as the job board states it. Interpretation (fit, pay, place) is Claude's job. */
export interface Job {
  /** Stable id used for de-duplication in the tracker, e.g. "greenhouse:anthropic:12345". */
  id: string;
  /** A key of config/ats.ts, or "manual" for any other page. */
  ats: string;
  board: string;
  company: string;
  title: string;
  location: string;
  workplace: string;
  compensation: string;
  url: string;
  applyUrl: string;
  description: string;
  postedAt?: string;
}

export interface Company {
  company: string;
  ats: string;
  board: string;
}
