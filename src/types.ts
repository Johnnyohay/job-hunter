export type Ats = "greenhouse" | "lever" | "ashby" | "manual";

export interface Job {
  /** Stable id used for de-duplication in the tracker, e.g. "greenhouse:anthropic:12345". */
  id: string;
  ats: Ats;
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
  ats: Ats;
  board: string;
}
