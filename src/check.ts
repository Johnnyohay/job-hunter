// Credential-free smoke test: fetches the job boards and shows what passes the keyword filter.
// Usage: npm run check -- greenhouse:anthropic lever:palantir ashby:lovable
import { passesPrefilter } from "./filter.ts";
import { fetchBoard } from "./sources.ts";

const args = process.argv.slice(2);
const boards = (args.length ? args : ["greenhouse:anthropic", "lever:palantir", "ashby:lovable"]).map((a) => {
  const [ats, board] = a.split(":");
  return { ats, board, company: board };
});

for (const b of boards) {
  try {
    const jobs = await fetchBoard(b);
    const passing = jobs.filter((j) => passesPrefilter(j));
    console.log(`${b.ats}:${b.board}: ${jobs.length} open, ${passing.length} pass the filter`);
    for (const j of passing.slice(0, 8)) console.log(`   ${j.title} | ${j.location} | ${j.description.length} chars`);
  } catch (e) {
    console.log(`${b.ats}:${b.board}: ERROR ${(e as Error).message}`);
  }
}
