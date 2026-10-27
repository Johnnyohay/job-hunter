// Applies the tracker's column layout and types. Safe to re-run. When the code's columns have changed, every
// row is rewritten into the current columns, matched by column name, so nothing is lost or shifted.
// Usage: npm run tracker:format
import { env } from "./env.ts";
import { COLUMNS, formatTracker, readTracker, rewriteTracker, type Row } from "./tracker.ts";

/** Columns that were renamed: old name -> current name. */
const RENAMED: Record<string, string> = { Location: "Locations (as posted)", Compensation: "Comp (as posted)" };

const id = env("JOB_AGENT_TRACKER_ID");
const rows = await readTracker(id, { allowOldColumns: true });
const current: Row[] = rows.map((old) => {
  const row: Record<string, string> = Object.fromEntries(COLUMNS.map((c) => [c, ""]));
  for (const [name, value] of Object.entries(old)) {
    const target = RENAMED[name] ?? name;
    if (target in row && value) row[target] = String(value);
  }
  return row;
});

await rewriteTracker(id, current);
await formatTracker(id);
console.log(`Tracker: ${current.length} rows in ${COLUMNS.length} typed columns.`);
