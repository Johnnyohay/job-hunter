import Anthropic from "@anthropic-ai/sdk";
import { betaZodOutputFormat } from "@anthropic-ai/sdk/helpers/beta/zod";
import { z } from "zod";
import { MODEL } from "./env.ts";
import type { Profile } from "./profile.ts";
import type { Job } from "./types.ts";

const client = new Anthropic();

// Server-side fallback: if a request is declined, the API retries it on a fallback model in the same call.
const FALLBACK = { betas: ["server-side-fallback-2026-07-01"], fallbacks: "default" as const };

const SYSTEM = `You are a job-search assistant working for one candidate. Their CV, LinkedIn profile, "About Me" notes and job preferences are in the first message.

Ground rules:
- Facts about the candidate come only from those documents. Never invent or inflate experience, metrics, titles, dates, skills, credentials or work authorization.
- When something you need is not in the documents, say so instead of guessing.
- Write in plain, confident, specific language. No buzzwords and no flattery of the company.`;

/** The candidate's documents, identical on every call so the prefix is cached. */
export function profileBlocks(p: Profile): Anthropic.Beta.BetaContentBlockParam[] {
  const blocks: Anthropic.Beta.BetaContentBlockParam[] = [];
  if (p.cvPdf) {
    blocks.push({ type: "document", title: "CV", source: { type: "base64", media_type: "application/pdf", data: p.cvPdf.toString("base64") } });
  } else if (p.cvText) {
    blocks.push({ type: "document", title: "CV", source: { type: "text", media_type: "text/plain", data: p.cvText } });
  }
  if (p.linkedinPdf) {
    blocks.push({ type: "document", title: "LinkedIn profile", source: { type: "base64", media_type: "application/pdf", data: p.linkedinPdf.toString("base64") } });
  }
  blocks.push({
    type: "text",
    text: `<about_me>\n${p.aboutMe || "(empty)"}\n</about_me>\n\n<job_preferences>\n${p.preferences}\n</job_preferences>`,
    cache_control: { type: "ephemeral", ttl: "1h" },
  });
  return blocks;
}

function jobText(job: Job): string {
  return `<job>
Company: ${job.company}
Title: ${job.title}
Location: ${job.location || "unknown"} ${job.workplace ? `(${job.workplace})` : ""}
Compensation: ${job.compensation || "not listed"}
URL: ${job.url}

${job.description.slice(0, 30000)}
</job>`;
}

const Fit = z.object({
  fit: z.number().describe("0-100: how strong a candidate they are for this role AND how well it matches their preferences"),
  recommendation: z.enum(["apply", "maybe", "skip"]),
  why_it_fits: z.string().describe("1-2 sentences citing concrete CV evidence"),
  gaps: z.string().describe("1-2 sentences: missing requirements, risks, or preference conflicts; empty if none"),
  deal_breakers: z.array(z.string()).describe("Preference deal-breakers this job hits (location, seniority, sponsorship, comp...)"),
});
export type FitResult = z.infer<typeof Fit>;

export async function scoreJob(profile: Anthropic.Beta.BetaContentBlockParam[], job: Job): Promise<FitResult | null> {
  const res = await client.beta.messages.parse({
    model: MODEL,
    max_tokens: 8000,
    ...FALLBACK,
    output_config: { effort: "low", format: betaZodOutputFormat(Fit) },
    system: SYSTEM,
    messages: [{
      role: "user",
      content: [...profile, { type: "text", text: `Score this job for the candidate. Be strict: a hard requirement they clearly lack, or any deal-breaker, caps the score at 50.\n\n${jobText(job)}` }],
    }],
  });
  return res.stop_reason === "refusal" ? null : res.parsed_output;
}

const Materials = z.object({
  cover_letter: z.string().describe("250-350 words, addressed to the hiring team, specific to this role, only true claims"),
  cv_tailoring: z.array(z.string()).describe("3-6 concrete edits to the CV for this role (reorder, emphasize, reword); never invent"),
  form_answers: z.array(z.object({ question: z.string(), answer: z.string() }))
    .describe("Answers to questions this application is likely to ask (why this company, why this role, relevant project...)"),
  outreach_note: z.string().describe("LinkedIn connection note to the hiring manager, under 280 characters"),
  needs_from_candidate: z.array(z.string()).describe("Information missing from the documents that this application needs"),
});
export type MaterialsResult = z.infer<typeof Materials>;

export async function draftMaterials(profile: Anthropic.Beta.BetaContentBlockParam[], job: Job): Promise<MaterialsResult | null> {
  const stream = client.beta.messages.stream({
    model: MODEL,
    max_tokens: 32000,
    ...FALLBACK,
    output_config: { effort: "medium", format: betaZodOutputFormat(Materials) },
    system: SYSTEM,
    messages: [{ role: "user", content: [...profile, { type: "text", text: `Draft the application materials for this job.\n\n${jobText(job)}` }] }],
  });
  const res = await stream.finalMessage();
  if (res.stop_reason === "refusal") return null;
  const text = res.content.flatMap((b) => (b.type === "text" ? [b.text] : [])).join("");
  return Materials.parse(JSON.parse(text));
}

const HiringManager = z.object({
  name: z.string(),
  title: z.string(),
  linkedin_url: z.string(),
  confidence: z.enum(["high", "medium", "low", "none"]),
  evidence: z.string(),
});
export type HiringManagerResult = z.infer<typeof HiringManager>;

/**
 * Finds the likely hiring manager with Claude's web search. It reads public search results only:
 * LinkedIn itself is never scraped and nobody is contacted.
 */
export async function findHiringManager(job: Job): Promise<HiringManagerResult | null> {
  const messages: Anthropic.Beta.BetaMessageParam[] = [{
    role: "user",
    content: `Find the most likely hiring manager for this job: the person the role reports to (e.g. head of the team or function), not a recruiter.

Use web search: the job post itself, the company's team/leadership pages, news, and search results for LinkedIn profiles (for example: site:linkedin.com/in "${job.company}" plus the function's leader title).
Only report a LinkedIn URL that actually appeared in a search result; never construct one. If you cannot identify someone with reasonable confidence, use confidence "none" and empty strings.

Finish with only a JSON object: {"name": "", "title": "", "linkedin_url": "", "confidence": "high|medium|low|none", "evidence": "one sentence on why this person"}

${jobText({ ...job, description: job.description.slice(0, 6000) })}`,
  }];

  for (let turn = 0; turn < 4; turn++) {
    const res = await client.beta.messages.create({
      model: MODEL,
      max_tokens: 16000,
      ...FALLBACK,
      output_config: { effort: "medium" },
      tools: [{ type: "web_search_20260209", name: "web_search", max_uses: 6 }],
      messages,
    });
    if (res.stop_reason === "pause_turn") {
      messages.push({ role: "assistant", content: res.content });
      continue;
    }
    if (res.stop_reason === "refusal") return null;
    const text = res.content.flatMap((b) => (b.type === "text" ? [b.text] : [])).join("");
    const json = text.match(/\{[\s\S]*\}/g)?.at(-1);
    const parsed = json ? HiringManager.safeParse(JSON.parse(json)) : undefined;
    if (!parsed?.success) return null;
    const hm = parsed.data;
    if (hm.linkedin_url && !/^https:\/\/([a-z]{2,3}\.)?linkedin\.com\/in\//i.test(hm.linkedin_url)) hm.linkedin_url = "";
    return hm;
  }
  return null;
}
