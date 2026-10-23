// Section headings of a materials doc. Claude Code writes the doc (.claude/commands/daily.md);
// `npm run apply` reads the cover letter back out of it.
export const COVER_LETTER_HEADING = "COVER LETTER";
export const AFTER_COVER_LETTER_HEADING = "CV TAILORING";

/** Pulls the cover letter back out of a materials doc (as plain text). */
export function coverLetterFrom(doc: string): string {
  const start = doc.indexOf(COVER_LETTER_HEADING);
  if (start < 0) return "";
  const rest = doc.slice(start + COVER_LETTER_HEADING.length);
  return rest.split(new RegExp(`\\n\\s*${AFTER_COVER_LETTER_HEADING}\\s*\\n`))[0].trim();
}
