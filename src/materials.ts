import type { HiringManagerResult, MaterialsResult } from "./claude.ts";
import type { Job } from "./types.ts";

export const COVER_LETTER_HEADING = "COVER LETTER";

export function materialsDoc(job: Job, m: MaterialsResult, hm: HiringManagerResult | null): string {
  const hmLines = hm && hm.confidence !== "none"
    ? [`${hm.name}, ${hm.title} (confidence: ${hm.confidence})`, hm.linkedin_url, hm.evidence]
    : ["Not identified."];
  return [
    `${job.company}: ${job.title}`,
    job.url,
    "",
    "NEEDS FROM YOU",
    ...(m.needs_from_candidate.length ? m.needs_from_candidate.map((n) => `• ${n}`) : ["Nothing; ready to review."]),
    "",
    "HIRING MANAGER",
    ...hmLines.filter(Boolean),
    "",
    "LINKEDIN NOTE (send yourself; the agent never contacts anyone)",
    m.outreach_note,
    "",
    COVER_LETTER_HEADING,
    m.cover_letter,
    "",
    "CV TAILORING",
    ...m.cv_tailoring.map((t) => `• ${t}`),
    "",
    "LIKELY QUESTIONS",
    ...m.form_answers.flatMap((qa) => [`Q: ${qa.question}`, `A: ${qa.answer}`, ""]),
  ].join("\n");
}

/** Pulls the cover letter back out of a materials doc (exported as plain text). */
export function coverLetterFrom(doc: string): string {
  const start = doc.indexOf(COVER_LETTER_HEADING);
  if (start < 0) return "";
  return doc.slice(start + COVER_LETTER_HEADING.length).split(/\n\s*CV TAILORING\s*\n/)[0].trim();
}
