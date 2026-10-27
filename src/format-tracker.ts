// Applies the tracker's column types and layout, and re-types existing rows. Safe to re-run.
// Usage: npm run tracker:format
import { env } from "./env.ts";
import { formatTracker, retypeRows } from "./tracker.ts";

const id = env("JOB_AGENT_TRACKER_ID");
await formatTracker(id);
console.log(`Formatted the tracker and re-typed ${await retypeRows(id)} rows.`);
