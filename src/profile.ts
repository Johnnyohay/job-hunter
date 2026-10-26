import { env } from "./env.ts";
import { FOLDER, GDOC, GSHEET, docText, fileBytes, listFolder, sheetRecords, type DriveFile } from "./google.ts";
import { field } from "./text.ts";
import type { Ats, Company } from "./types.ts";

export interface Profile {
  cvText?: string;
  cvPdf?: Buffer;
  cvPdfId?: string;
  linkedinPdf?: Buffer;
  aboutMe: string;
  preferences: string;
  linkedinUrl: string;
  minFit?: number;
  maxPerDay?: number;
  trackerId: string;
  targetsId: string;
  companiesId: string;
  applicationsFolderId: string;
}

function pick(files: DriveFile[], name: RegExp, mime?: string): DriveFile | undefined {
  return files.find((f) => name.test(f.name) && (!mime || f.mimeType === mime));
}

function need<T>(value: T | undefined, what: string): T {
  if (!value) throw new Error(`Not found in the "Job Application Agent" Drive folder: ${what}`);
  return value;
}

function num(s: string): number | undefined {
  const n = parseInt(s.replace(/[^\d]/g, ""), 10);
  return Number.isFinite(n) ? n : undefined;
}

/** Reads everything the agent knows about the user from the Drive folder. */
export async function loadProfile(): Promise<Profile> {
  const root = await listFolder(env("JOB_AGENT_FOLDER_ID"));
  const profileFolder = need(pick(root, /^profile$/i, FOLDER), "Profile folder");
  const profileFiles = await listFolder(profileFolder.id);

  const cvPdf = pick(profileFiles, /^cv\.pdf$/i) ?? profileFiles.find((f) => f.mimeType === "application/pdf" && !/linkedin/i.test(f.name));
  const cvDoc = pick(profileFiles, /^cv$/i, GDOC);
  const linkedinPdf = profileFiles.find((f) => f.mimeType === "application/pdf" && /linkedin/i.test(f.name));
  if (!cvPdf && !cvDoc) throw new Error('No CV yet: add "CV.pdf" (or a Google Doc named "CV") to the Profile folder.');

  const prefsDoc = need(pick(root, /^job preferences$/i, GDOC), '"Job Preferences" doc');
  const aboutDoc = pick(profileFiles, /^about me/i, GDOC);
  const [preferences, aboutMe, cvText, cvBytes, linkedinBytes] = await Promise.all([
    docText(prefsDoc.id),
    aboutDoc ? docText(aboutDoc.id) : Promise.resolve(""),
    cvDoc ? docText(cvDoc.id) : Promise.resolve(undefined),
    cvPdf ? fileBytes(cvPdf.id) : Promise.resolve(undefined),
    linkedinPdf ? fileBytes(linkedinPdf.id) : Promise.resolve(undefined),
  ]);

  return {
    cvText,
    cvPdf: cvBytes,
    cvPdfId: cvPdf?.id,
    linkedinPdf: linkedinBytes,
    aboutMe,
    preferences,
    linkedinUrl: field(preferences, "LinkedIn"),
    minFit: num(field(preferences, "Minimum fit score")),
    maxPerDay: num(field(preferences, "Max applications per day")),
    // The agent's own tracker and Applications folder (created by `npm run bridge`; the only files it can edit).
    trackerId: env("JOB_AGENT_TRACKER_ID"),
    targetsId: need(pick(root, /^target positions$/i, GSHEET), '"Target Positions" sheet').id,
    companiesId: need(pick(root, /^companies to watch$/i, GSHEET), '"Companies to Watch" sheet').id,
    applicationsFolderId: env("JOB_AGENT_APPLICATIONS_ID"),
  };
}

export async function loadCompanies(p: Profile): Promise<Company[]> {
  return (await sheetRecords(p.companiesId))
    .filter((r) => r.Board && !/^(no|n|false|0)$/i.test(r.Active ?? ""))
    .map((r) => ({ company: r.Company || r.Board, ats: (r.ATS || "").toLowerCase() as Ats, board: r.Board }));
}

export async function loadTargets(p: Profile): Promise<{ url: string; company: string; title: string }[]> {
  return (await sheetRecords(p.targetsId))
    .filter((r) => /^https?:\/\//.test(r["Job URL"] ?? ""))
    .map((r) => ({ url: r["Job URL"], company: r.Company ?? "", title: r.Title ?? "" }));
}
