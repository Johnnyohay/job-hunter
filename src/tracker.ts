import { sheetAppend, sheetBatchUpdate, sheetMeta, sheetRows, sheetSet } from "./google.ts";

type Kind = "text" | "date" | "number" | "decimal" | "money" | "url" | "longtext";

/** Every tracker column and the type of data it holds. Order = column order in the sheet. */
const SCHEMA = [
  ["Job ID", "text", 150],
  ["Found", "date", 95],
  ["Company", "text", 110],
  ["Title", "text", 260],
  ["Workplace", "text", 85],
  ["City", "text", 110],
  ["State", "text", 110],
  ["Country", "text", 105],
  ["Latitude", "decimal", 80],
  ["Longitude", "decimal", 85],
  ["# Locations", "number", 85],
  ["Locations (as posted)", "text", 200],
  ["Comp Min", "money", 90],
  ["Comp Max", "money", 90],
  ["Currency", "text", 70],
  ["Comp (as posted)", "text", 200],
  ["Fit", "number", 50],
  ["Status", "text", 130],
  ["Why it fits", "longtext", 320],
  ["Gaps / risks", "longtext", 320],
  ["Hiring Manager", "text", 200],
  ["HM LinkedIn", "url", 160],
  ["Job URL", "url", 160],
  ["Apply URL", "url", 160],
  ["Materials", "url", 160],
  ["Applied On", "date", 95],
  ["Last Update", "date", 95],
  ["Notes", "longtext", 280],
] as const satisfies readonly (readonly [string, Kind, number])[];

export const COLUMNS = SCHEMA.map(([name]) => name);
export type Column = (typeof SCHEMA)[number][0];
export type Row = Partial<Record<Column, string>>;

/** Statuses the agent writes. You can also set your own (Interview, Rejected, Offer...); the agent leaves those alone. */
export const STATUS = {
  notAFit: "Not a fit",
  possible: "Possible fit",
  shortlisted: "Shortlisted",
  ready: "Ready for review",
  approved: "Approved",
  applied: "Applied",
  skipped: "Skipped",
} as const;
const STATUS_CHOICES = [...Object.values(STATUS), "Interview", "Rejected", "Offer", "Withdrawn"];

/** Today's date on this machine, as yyyy-mm-dd. */
export const today = () => new Date().toLocaleDateString("en-CA");

/**
 * The cell as the sheet should parse it (written with USER_ENTERED): dates and numbers stay bare so Sheets stores
 * real dates and numbers; everything else gets a leading apostrophe, so it is always stored as text (never a formula,
 * a number or a date by accident). The apostrophe is not part of the value.
 */
function cell(kind: Kind, value: string | undefined): string {
  const v = (value ?? "").trim();
  if (!v) return "";
  if (kind === "date" && /^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
  if ((kind === "number" || kind === "decimal" || kind === "money") && /^-?\d+(\.\d+)?$/.test(v)) return v;
  if (kind === "url" && /^https?:\/\/\S+$/.test(v)) return v;
  return `'${v}`;
}

const toCells = (r: Row) => SCHEMA.map(([name, kind]) => cell(kind, r[name]));

export type TrackedRow = Row & Record<string, string> & { rowNumber: number };

/** Rows keyed by the sheet's own header, so a sheet with older columns can still be read (and migrated). */
export async function readTracker(spreadsheetId: string, { allowOldColumns = false } = {}): Promise<TrackedRow[]> {
  const rows = await sheetRows(spreadsheetId);
  let header = rows[0] ?? [];
  if (!header.length) {
    await sheetSet(spreadsheetId, 1, 1, [[...COLUMNS]]);
    await formatTracker(spreadsheetId);
    header = [...COLUMNS];
  } else if (!allowOldColumns && COLUMNS.some((c, i) => header[i] !== c)) {
    throw new Error("The tracker's columns are from an older version. Run: npm run tracker:format");
  }
  return rows.slice(1).map((r, i) => ({
    ...Object.fromEntries(header.map((h, j) => [h, r[j] ?? ""])),
    rowNumber: i + 2,
  }) as TrackedRow);
}

export async function appendRows(spreadsheetId: string, rows: Row[]): Promise<void> {
  if (!rows.length) return;
  await sheetAppend(spreadsheetId, rows.map(toCells));
}

export async function updateRow(spreadsheetId: string, rowNumber: number, changes: Row): Promise<void> {
  for (const [c, v] of Object.entries({ ...changes, "Last Update": today() }) as [Column, string][]) {
    const i = COLUMNS.indexOf(c);
    await sheetSet(spreadsheetId, rowNumber, i + 1, [[cell(SCHEMA[i][1], v)]]);
  }
}

/** Rewrites the whole table in the current columns: header plus every row, typed. */
export async function rewriteTracker(spreadsheetId: string, rows: Row[]): Promise<void> {
  await sheetSet(spreadsheetId, 1, 1, [[...COLUMNS], ...rows.map(toCells)]);
}

/**
 * Column types, widths, header, Status dropdown, Fit color scale and a filter. Safe to re-run: it replaces
 * the sheet's conditional formats and validation instead of adding to them.
 */
export async function formatTracker(spreadsheetId: string): Promise<void> {
  const { sheetId, conditionalFormats, hasFilter } = await sheetMeta(spreadsheetId);
  const col = (i: number) => ({ sheetId, startColumnIndex: i, endColumnIndex: i + 1 });
  const body = (i: number) => ({ ...col(i), startRowIndex: 1 });
  const fmt: Record<Kind, object> = {
    date: { numberFormat: { type: "DATE", pattern: "yyyy-mm-dd" }, horizontalAlignment: "CENTER" },
    number: { numberFormat: { type: "NUMBER", pattern: "0" }, horizontalAlignment: "CENTER" },
    decimal: { numberFormat: { type: "NUMBER", pattern: "0.0000" }, horizontalAlignment: "RIGHT" },
    money: { numberFormat: { type: "NUMBER", pattern: "#,##0" }, horizontalAlignment: "RIGHT" },
    text: { numberFormat: { type: "TEXT" }, wrapStrategy: "CLIP" },
    url: { numberFormat: { type: "TEXT" }, wrapStrategy: "CLIP" },
    longtext: { numberFormat: { type: "TEXT" }, wrapStrategy: "WRAP" },
  };
  const fitIndex = COLUMNS.indexOf("Fit");
  const statusIndex = COLUMNS.indexOf("Status");

  await sheetBatchUpdate(spreadsheetId, [
    ...Array.from({ length: conditionalFormats }, () => ({ deleteConditionalFormatRule: { sheetId, index: 0 } })),
    ...(hasFilter ? [{ clearBasicFilter: { sheetId } }] : []),
    { setDataValidation: { range: { sheetId } } }, // clears old dropdowns (columns may have moved)
    {
      updateSheetProperties: {
        properties: { sheetId, title: "Tracker", gridProperties: { frozenRowCount: 1 } },
        fields: "title,gridProperties.frozenRowCount",
      },
    },
    {
      repeatCell: {
        range: { sheetId, startRowIndex: 0, endRowIndex: 1 },
        cell: { userEnteredFormat: { textFormat: { bold: true }, backgroundColor: { red: 0.9, green: 0.92, blue: 0.95 }, verticalAlignment: "MIDDLE", wrapStrategy: "WRAP" } },
        fields: "userEnteredFormat(textFormat,backgroundColor,verticalAlignment,wrapStrategy)",
      },
    },
    ...SCHEMA.flatMap(([, kind, width], i) => [
      {
        repeatCell: {
          range: body(i),
          cell: { userEnteredFormat: { ...fmt[kind], verticalAlignment: "TOP" } },
          fields: "userEnteredFormat(numberFormat,horizontalAlignment,wrapStrategy,verticalAlignment)",
        },
      },
      {
        updateDimensionProperties: {
          range: { sheetId, dimension: "COLUMNS", startIndex: i, endIndex: i + 1 },
          properties: { pixelSize: width },
          fields: "pixelSize",
        },
      },
    ]),
    {
      setDataValidation: {
        range: body(statusIndex),
        rule: {
          condition: { type: "ONE_OF_LIST", values: STATUS_CHOICES.map((userEnteredValue) => ({ userEnteredValue })) },
          showCustomUi: true,
          strict: false,
        },
      },
    },
    {
      addConditionalFormatRule: {
        index: 0,
        rule: {
          ranges: [body(fitIndex)],
          gradientRule: {
            minpoint: { type: "NUMBER", value: "0", color: { red: 0.96, green: 0.8, blue: 0.8 } },
            midpoint: { type: "NUMBER", value: "50", color: { red: 1, green: 0.95, blue: 0.8 } },
            maxpoint: { type: "NUMBER", value: "100", color: { red: 0.72, green: 0.88, blue: 0.75 } },
          },
        },
      },
    },
    { setBasicFilter: { filter: { range: { sheetId, startRowIndex: 0, startColumnIndex: 0, endColumnIndex: COLUMNS.length } } } },
  ]);
}
