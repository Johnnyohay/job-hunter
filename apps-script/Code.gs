/**
 * Job Agent bridge: lets the local agent read the "Job Application Agent" Drive folder and keep its own
 * tracker and materials docs, without Google Cloud credentials. Deployed as a web app (npm run bridge:deploy).
 *
 * Least privilege, enforced by Google through the scopes in appsscript.json:
 * - drive.readonly: it can read your files but never change or delete them;
 * - drive.file: it can only create and edit files it created itself (the tracker and materials docs).
 * On top of that, every request must carry TOKEN, and reads are limited to ROOT_FOLDER_ID and the agent's own files.
 */
const TOKEN = "__TOKEN__";
const ROOT_FOLDER_ID = "__FOLDER_ID__";

const DRIVE = "https://www.googleapis.com/drive/v3/files";
const UPLOAD = "https://www.googleapis.com/upload/drive/v3/files";
const SHEETS = "https://sheets.googleapis.com/v4/spreadsheets";
const FOLDER = "application/vnd.google-apps.folder";

/** Opening the web app URL in a browser shows this. */
function doGet() {
  return ContentService.createTextOutput("Job agent bridge is running.");
}

function doPost(e) {
  let out;
  try {
    const req = JSON.parse(e.postData.contents);
    if (req.token !== TOKEN) throw new Error("bad token");
    const action = ACTIONS[req.action];
    if (!action) throw new Error("unknown action " + req.action);
    out = { ok: true, result: action(req) };
  } catch (err) {
    out = { ok: false, error: String((err && err.message) || err) };
  }
  return ContentService.createTextOutput(JSON.stringify(out)).setMimeType(ContentService.MimeType.JSON);
}

const ACTIONS = {
  list: ({ folderId }) => {
    allowed(folderId);
    const q = encodeURIComponent(`'${folderId}' in parents and trashed = false`);
    return api("get", `${DRIVE}?q=${q}&fields=files(id,name,mimeType)&pageSize=1000`).files;
  },

  docText: ({ id }) => {
    allowed(id);
    return api("get", `${DRIVE}/${id}/export?mimeType=text/plain`, null, true).getContentText();
  },

  bytes: ({ id }) => {
    allowed(id);
    return Utilities.base64Encode(api("get", `${DRIVE}/${id}?alt=media`, null, true).getContent());
  },

  values: ({ id, render }) => {
    allowed(id);
    const option = render === "raw" ? "?valueRenderOption=UNFORMATTED_VALUE" : "";
    return api("get", `${SHEETS}/${id}/values/A:AZ${option}`).values || [];
  },

  append: ({ id, rows }) => {
    if (!rows.length) return 0;
    api("post", `${SHEETS}/${id}/values/A1:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS`, { values: rows });
    return rows.length;
  },

  setRange: ({ id, row, col, values }) => {
    const range = encodeURIComponent(column(col) + row);
    api("put", `${SHEETS}/${id}/values/${range}?valueInputOption=USER_ENTERED`, { values });
    return true;
  },

  /** First tab's id, how many conditional format rules it has, and whether it has a filter. */
  meta: ({ id }) => {
    const sheet = api("get", `${SHEETS}/${id}?fields=sheets(properties(sheetId),conditionalFormats,basicFilter)`).sheets[0];
    return { sheetId: sheet.properties.sheetId, conditionalFormats: (sheet.conditionalFormats || []).length, hasFilter: !!sheet.basicFilter };
  },

  /** Formatting requests (Sheets API batchUpdate). drive.file limits this to sheets the agent created. */
  batchUpdate: ({ id, requests }) => {
    api("post", `${SHEETS}/${id}:batchUpdate`, { requests });
    return true;
  },

  createDoc: ({ folderId, name, text }) => {
    const meta = { name, mimeType: "application/vnd.google-apps.document", parents: [folderId] };
    const body = "--b\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n" + JSON.stringify(meta) +
      "\r\n--b\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n" + text + "\r\n--b--";
    const res = UrlFetchApp.fetch(`${UPLOAD}?uploadType=multipart&fields=id,webViewLink`, {
      method: "post",
      contentType: "multipart/related; boundary=b",
      payload: Utilities.newBlob(body).getBytes(),
      headers: { Authorization: "Bearer " + ScriptApp.getOAuthToken() },
      muteHttpExceptions: true,
    });
    if (res.getResponseCode() >= 300) throw new Error("create doc: " + res.getContentText().slice(0, 300));
    return JSON.parse(res.getContentText()).webViewLink;
  },

  /** Creates the agent's own tracker sheet and Applications folder (the only files it may edit). */
  setup: () => {
    const make = (name, mimeType) => {
      try {
        return api("post", `${DRIVE}?fields=id,webViewLink`, { name, mimeType, parents: [ROOT_FOLDER_ID] });
      } catch (e) {
        // Not allowed to add to a folder the script didn't create: put it in My Drive instead.
        return api("post", `${DRIVE}?fields=id,webViewLink`, { name, mimeType });
      }
    };
    const tracker = make("Application Tracker", "application/vnd.google-apps.spreadsheet");
    const applications = make("Applications", FOLDER);
    own(tracker.id);
    own(applications.id);
    return { trackerId: tracker.id, trackerUrl: tracker.webViewLink, applicationsId: applications.id, applicationsUrl: applications.webViewLink };
  },
};

function api(method, url, payload, raw) {
  const opts = { method, headers: { Authorization: "Bearer " + ScriptApp.getOAuthToken() }, muteHttpExceptions: true };
  if (payload) {
    opts.contentType = "application/json";
    opts.payload = JSON.stringify(payload);
  }
  const res = UrlFetchApp.fetch(url, opts);
  if (res.getResponseCode() >= 300) {
    throw new Error(`${method} ${url.split("?")[0]}: ${res.getResponseCode()} ${res.getContentText().slice(0, 300)}`);
  }
  return raw ? res : JSON.parse(res.getContentText() || "{}");
}

function column(n) {
  let s = "";
  for (; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
  return s;
}

/** Files and folders the agent created; reads are allowed inside these and inside ROOT_FOLDER_ID. */
function ownIds() {
  return JSON.parse(PropertiesService.getScriptProperties().getProperty("own") || "[]");
}

function own(id) {
  PropertiesService.getScriptProperties().setProperty("own", JSON.stringify(ownIds().concat([id])));
}

/** Throws unless id is ROOT_FOLDER_ID or the agent's own files, or somewhere beneath them. */
function allowed(id) {
  const roots = [ROOT_FOLDER_ID].concat(ownIds());
  let frontier = [id];
  for (let depth = 0; depth < 6 && frontier.length; depth++) {
    if (frontier.some((f) => roots.indexOf(f) >= 0)) return id;
    frontier = frontier.flatMap((f) => api("get", `${DRIVE}/${f}?fields=parents`).parents || []);
  }
  throw new Error("outside the Job Application Agent folder: " + id);
}
