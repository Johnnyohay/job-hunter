// Cheap keyword pre-filter applied before any job reaches Claude.
// A job passes if its title matches any `include` term and no `exclude` term (whole words, case-insensitive).
// The real judgment (fit, seniority, preferences) happens in Claude against my Drive docs.
export const search = {
  include: [
    "deployment", "deployed", "strategy", "operations", "bizops", "business operations", "solutions",
    "customer success", "technical account", "implementation", "engagement manager", "program manager",
    "product operations", "gtm", "chief of staff", "ai",
  ],
  exclude: [
    "intern", "internship", "software engineer", "data engineer", "recruiter", "counsel", "account executive",
    "director", "vice president", "vp", "principal",
  ],
  // A job passes if its location mentions any of these (whole words), or it has no location.
  // "Remote - USA" passes via "usa"; "Remote - Australia" does not. Empty = everywhere.
  // Order matters: the first match is preferred as a job's primary place.
  locations: ["boston", "massachusetts", "new york", "nyc", "united states", "usa", "us", "north america"],
  limits: {
    maxScoredPerRun: 25, // at most this many new jobs scored per day (keeps the run inside my Claude plan)
    maxTailoredPerRun: 5, // default; "Max applications per day" in Job Preferences overrides
    minFit: 70, // default; "Minimum fit score" in Job Preferences overrides
  },
};
