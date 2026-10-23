/**
 * Job Agent bridge: lets the local agent read and write the "Job Application Agent" Drive folder
 * without Google Cloud credentials. Deploy once as a web app (see README, "Apps Script bridge").
 *
 * Every request must carry TOKEN, and only files inside ROOT_FOLDER_ID (or its subfolders) can be touched.
 */
const TOKEN = "__TOKEN__";
const ROOT_FOLDER_ID = "__FOLDER_ID__";

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
    const folder = DriveApp.getFolderById(allowed(folderId));
    const out = [];
    for (const it = folder.getFolders(); it.hasNext(); ) {
      const f = it.next();
      out.push({ id: f.getId(), name: f.getName(), mimeType: "application/vnd.google-apps.folder" });
    }
    for (const it = folder.getFiles(); it.hasNext(); ) {
      const f = it.next();
      out.push({ id: f.getId(), name: f.getName(), mimeType: f.getMimeType() });
    }
    return out;
  },

  docText: ({ id }) => DocumentApp.openById(allowed(id)).getBody().getText(),

  bytes: ({ id }) => Utilities.base64Encode(DriveApp.getFileById(allowed(id)).getBlob().getBytes()),

  values: ({ id }) => firstSheet(id).getDataRange().getDisplayValues(),

  append: ({ id, rows }) => {
    if (!rows.length) return 0;
    const lock = LockService.getScriptLock();
    lock.waitLock(30000);
    try {
      const sheet = firstSheet(id);
      sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows.map(asText));
      return rows.length;
    } finally {
      lock.releaseLock();
    }
  },

  setRange: ({ id, row, col, values }) => {
    firstSheet(id).getRange(row, col, values.length, values[0].length).setValues(values.map(asText));
    return true;
  },

  createDoc: ({ folderId, name, text }) => {
    const folder = DriveApp.getFolderById(allowed(folderId));
    const doc = DocumentApp.create(name);
    doc.getBody().setText(text);
    doc.saveAndClose();
    const file = DriveApp.getFileById(doc.getId());
    file.moveTo(folder);
    return file.getUrl();
  },
};

function firstSheet(id) {
  return SpreadsheetApp.openById(allowed(id)).getSheets()[0];
}

/** Stores cells as plain text, so "=..." or "+1 617..." is never read as a formula or number. */
function asText(row) {
  return row.map((v) => {
    const s = v == null ? "" : String(v);
    return /^[=+\-@]/.test(s) ? "'" + s : s;
  });
}

/** Throws unless the file or folder is ROOT_FOLDER_ID or somewhere beneath it. */
function allowed(id) {
  if (id === ROOT_FOLDER_ID) return id;
  const seen = {};
  let frontier = [id];
  for (let depth = 0; depth < 6 && frontier.length; depth++) {
    const next = [];
    for (const current of frontier) {
      const item = current === id ? fileOrFolder(id) : DriveApp.getFolderById(current);
      for (const parents = item.getParents(); parents.hasNext(); ) {
        const p = parents.next().getId();
        if (p === ROOT_FOLDER_ID) return id;
        if (!seen[p]) {
          seen[p] = true;
          next.push(p);
        }
      }
    }
    frontier = next;
  }
  throw new Error("outside the Job Application Agent folder: " + id);
}

function fileOrFolder(id) {
  try {
    return DriveApp.getFileById(id);
  } catch (e) {
    return DriveApp.getFolderById(id);
  }
}
