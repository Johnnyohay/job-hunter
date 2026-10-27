// Google Drive and Sheets through the Apps Script bridge (apps-script/Code.gs): no Cloud credentials needed.
import { env } from "./env.ts";

async function call<T>(action: string, args: Record<string, unknown>): Promise<T> {
  const res = await fetch(env("JOB_AGENT_SCRIPT_URL"), {
    method: "POST",
    headers: { "content-type": "text/plain" },
    body: JSON.stringify({ token: env("JOB_AGENT_TOKEN"), action, ...args }),
  });
  const text = await res.text();
  let body: { ok: boolean; result?: T; error?: string };
  try {
    body = JSON.parse(text);
  } catch {
    throw new Error(`Apps Script bridge returned HTTP ${res.status} without JSON. Is it deployed as a web app with access "Anyone"?`);
  }
  if (!body.ok) throw new Error(`Apps Script bridge (${action}): ${body.error}`);
  return body.result as T;
}

export interface DriveFile {
  id: string;
  name: string;
  mimeType: string;
}

export const FOLDER = "application/vnd.google-apps.folder";
export const GDOC = "application/vnd.google-apps.document";
export const GSHEET = "application/vnd.google-apps.spreadsheet";

export const listFolder = (folderId: string) => call<DriveFile[]>("list", { folderId });

export const docText = (id: string) => call<string>("docText", { id });

export async function fileBytes(id: string): Promise<Buffer> {
  return Buffer.from(await call<string>("bytes", { id }), "base64");
}

/** Creates a Google Doc with plain text in a folder; returns its link. */
export const createDoc = (folderId: string, name: string, text: string) => call<string>("createDoc", { folderId, name, text });

export interface AgentFiles {
  trackerId: string;
  trackerUrl: string;
  applicationsId: string;
  applicationsUrl: string;
}

/** Creates the agent's own tracker sheet and Applications folder. */
export const setupAgentFiles = () => call<AgentFiles>("setup", {});

/** All rows of the first tab, header row included. */
export const sheetRows = (id: string) => call<string[][]>("values", { id });

/** Same, but with the stored values (dates as serial numbers, numbers as numbers): shows the real cell types. */
export const sheetRawRows = (id: string) => call<unknown[][]>("values", { id, render: "raw" });

/** Appends rows (typed as if entered by hand: see tracker.ts `cell`) below the last row of the first tab. */
export const sheetAppend = (id: string, rows: string[][]) => call<number>("append", { id, rows });

/** Writes a block of values starting at a 1-based row and column of the first tab. */
export const sheetSet = (id: string, row: number, col: number, values: string[][]) =>
  call<boolean>("setRange", { id, row, col, values });

/** First tab's id plus what formatTracker needs to replace instead of duplicate. */
export const sheetMeta = (id: string) =>
  call<{ sheetId: number; conditionalFormats: number; hasFilter: boolean }>("meta", { id });

/** Sheets API batchUpdate requests (formatting, validation...). */
export const sheetBatchUpdate = (id: string, requests: object[]) => call<boolean>("batchUpdate", { id, requests });

/** Rows of the first tab as objects keyed by the header row. */
export async function sheetRecords(id: string): Promise<Record<string, string>[]> {
  const [header = [], ...rows] = await sheetRows(id);
  return rows
    .filter((r) => r.some((c) => c?.trim()))
    .map((r) => Object.fromEntries(header.map((h, i) => [h.trim(), (r[i] ?? "").trim()])));
}
