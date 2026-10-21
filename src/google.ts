import { google } from "googleapis";
import { env } from "./env.ts";

export const SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"];

function auth() {
  const client = new google.auth.OAuth2(env("GOOGLE_CLIENT_ID"), env("GOOGLE_CLIENT_SECRET"));
  client.setCredentials({ refresh_token: env("GOOGLE_REFRESH_TOKEN") });
  return client;
}

let clients: { drive: ReturnType<typeof google.drive>; sheets: ReturnType<typeof google.sheets> } | undefined;

export function gapi() {
  if (!clients) {
    const a = auth();
    clients = { drive: google.drive({ version: "v3", auth: a }), sheets: google.sheets({ version: "v4", auth: a }) };
  }
  return clients;
}

export interface DriveFile {
  id: string;
  name: string;
  mimeType: string;
}

export const FOLDER = "application/vnd.google-apps.folder";
export const GDOC = "application/vnd.google-apps.document";
export const GSHEET = "application/vnd.google-apps.spreadsheet";

export async function listFolder(folderId: string): Promise<DriveFile[]> {
  const res = await gapi().drive.files.list({
    q: `'${folderId}' in parents and trashed = false`,
    fields: "files(id,name,mimeType)",
    pageSize: 1000,
  });
  return (res.data.files ?? []) as DriveFile[];
}

export async function docText(fileId: string): Promise<string> {
  const res = await gapi().drive.files.export({ fileId, mimeType: "text/plain" }, { responseType: "text" });
  return String(res.data).replace(/^﻿/, "");
}

export async function fileBytes(fileId: string): Promise<Buffer> {
  const res = await gapi().drive.files.get({ fileId, alt: "media" }, { responseType: "arraybuffer" });
  return Buffer.from(res.data as ArrayBuffer);
}

export async function createDoc(folderId: string, name: string, text: string): Promise<string> {
  const res = await gapi().drive.files.create({
    requestBody: { name, mimeType: GDOC, parents: [folderId] },
    media: { mimeType: "text/plain", body: text },
    fields: "id,webViewLink",
  });
  return res.data.webViewLink ?? `https://docs.google.com/document/d/${res.data.id}/edit`;
}

/** All rows of the first tab, header row included. */
export async function sheetRows(spreadsheetId: string): Promise<string[][]> {
  const res = await gapi().sheets.spreadsheets.values.get({ spreadsheetId, range: "A:Z" });
  return (res.data.values ?? []) as string[][];
}

/** Rows of the first tab as objects keyed by the header row. */
export async function sheetRecords(spreadsheetId: string): Promise<Record<string, string>[]> {
  const [header = [], ...rows] = await sheetRows(spreadsheetId);
  return rows
    .filter((r) => r.some((c) => c?.trim()))
    .map((r) => Object.fromEntries(header.map((h, i) => [h.trim(), (r[i] ?? "").trim()])));
}
