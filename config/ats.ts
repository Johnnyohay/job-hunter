// Job boards, described as data. To support a new ATS, or follow a change in one, edit this file: no code changes.
//
// Each board's public API returns a list of open jobs. Paths say where each field sits in one job object:
// "location.name" reads job.location.name; "lists[].content" reads every element's content. A list of paths is
// joined. If the API stops returning a required field (id, title, url), the run reports it instead of guessing.
// Interpretation (pay, workplace, place) is not done here: Claude reads the raw text.

export interface AtsConfig {
  /** Public endpoint listing every open job on a board; {board} is the company's board name. */
  list: string;
  /** Path to the array of jobs in the response ("" when the response is the array). */
  jobs: string;
  fields: {
    id: string;
    title: string;
    url: string;
    location: string[];
    description: string[];
    /** Optional: the board's own application form, if it differs from url. Templates may use {url}, {board}, {id}. */
    applyUrl?: string;
    posted?: string;
    /** Pay and workplace exactly as the board states them, passed to Claude as-is. */
    pay?: string[];
    workplace?: string[];
  };
  /** Recognizes a posting URL: group 1 = board, group 2 = job id. */
  postingUrl: RegExp;
}

export const ATS: Record<string, AtsConfig> = {
  greenhouse: {
    list: "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true",
    jobs: "jobs",
    fields: {
      id: "id",
      title: "title",
      url: "absolute_url",
      applyUrl: "https://job-boards.greenhouse.io/{board}/jobs/{id}",
      location: ["location.name"],
      description: ["content"],
      posted: "first_published",
    },
    postingUrl: /greenhouse\.io\/(?:embed\/job_app\?for=)?([\w-]+)\/jobs\/(\d+)/,
  },
  lever: {
    list: "https://api.lever.co/v0/postings/{board}?mode=json",
    jobs: "",
    fields: {
      id: "id",
      title: "text",
      url: "hostedUrl",
      applyUrl: "applyUrl",
      location: ["categories.allLocations[]", "categories.location"],
      description: ["descriptionPlain", "lists[].text", "lists[].content", "additionalPlain"],
      posted: "createdAt",
      pay: ["salaryRange.min", "salaryRange.max", "salaryRange.currency", "salaryRange.interval"],
      workplace: ["workplaceType"],
    },
    postingUrl: /jobs\.lever\.co\/([\w-]+)\/([\w-]{36})/,
  },
  ashby: {
    list: "https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true",
    jobs: "jobs",
    fields: {
      id: "id",
      title: "title",
      url: "jobUrl",
      applyUrl: "{url}/application",
      location: ["location", "secondaryLocations[].location"],
      description: ["descriptionPlain"],
      posted: "publishedAt",
      pay: ["compensation.compensationTierSummary"],
      workplace: ["workplaceType"],
    },
    postingUrl: /jobs\.ashbyhq\.com\/([\w.-]+)\/([\w-]{36})/,
  },
};
