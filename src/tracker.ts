import { gapi, sheetRows } from "./google.ts";

export const COLUMNS = [
  "Job ID", "Found", "Company", "Title", "Location", "Workplace", "Compensation", "Fit", "Status",
  "Why it fits", "Gaps / risks", "Hiring Manager", "HM LinkedIn", "Job URL", "Apply URL", "Materials",
  "Applied On", "Last Update", "Notes",
] as const;
export type Column = (typeof COLUMNS)[number];
export type Row = Partial<Record<Column, string>>;

/** Statuses the agent writes. You can also set your own (Interview, Rejected, Offer...); the agent leaves those alone. */
export const STATUS = {
  notAFit: "Not a fit",
  shortlisted: "Shortlisted",
  ready: "Ready for review",
  approved: "Approved",
  applied: "Applied",
  skipped: "Skipped",
} as const;

const letter = (i: number) => String.fromCharCode(65 + i);
const LAST = letter(COLUMNS.length - 1);

export const today = () => new Date().toISOString().slice(0, 10);

export interface TrackedRow extends Row {
  rowNumber: number;
}

export async function readTracker(spreadsheetId: string): Promise<TrackedRow[]> {
  const rows = await sheetRows(spreadsheetId);
  const header = rows[0] ?? [];
  if (COLUMNS.some((c, i) => header[i] !== c)) {
    // Keeps the header in sync with the code (also upgrades the first version of the sheet).
    await gapi().sheets.spreadsheets.values.update({
      spreadsheetId,
      range: `A1:${LAST}1`,
      valueInputOption: "RAW",
      requestBody: { values: [[...COLUMNS]] },
    });
  }
  return rows.slice(1).map((r, i) => ({
    rowNumber: i + 2,
    ...Object.fromEntries(COLUMNS.map((c, j) => [c, r[j] ?? ""])),
  }));
}

export async function appendRows(spreadsheetId: string, rows: Row[]): Promise<void> {
  if (!rows.length) return;
  await gapi().sheets.spreadsheets.values.append({
    spreadsheetId,
    range: `A:${LAST}`,
    valueInputOption: "RAW",
    insertDataOption: "INSERT_ROWS",
    requestBody: { values: rows.map((r) => COLUMNS.map((c) => r[c] ?? "")) },
  });
}

export async function updateRow(spreadsheetId: string, rowNumber: number, changes: Row): Promise<void> {
  const data = Object.entries({ ...changes, "Last Update": today() }).map(([c, v]) => ({
    range: `${letter(COLUMNS.indexOf(c as Column))}${rowNumber}`,
    values: [[v ?? ""]],
  }));
  await gapi().sheets.spreadsheets.values.batchUpdate({
    spreadsheetId,
    requestBody: { valueInputOption: "RAW", data },
  });
}
