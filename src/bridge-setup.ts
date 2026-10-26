// One-time setup of the Apps Script bridge.
//   npm run bridge          -> creates a token, copies the ready-to-paste script to the clipboard
//   npm run bridge -- URL   -> saves the deployed web app URL and tests it
import { execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";

const ENV = ".env";

function setEnv(name: string, value: string) {
  const lines = existsSync(ENV) ? readFileSync(ENV, "utf8").split("\n").filter((l) => !l.startsWith(`${name}=`)) : [];
  while (lines.length && !lines.at(-1)) lines.pop();
  writeFileSync(ENV, [...lines, `${name}=${value}`, ""].join("\n"));
  process.env[name] = value;
}

try {
  process.loadEnvFile(ENV);
} catch {
  // first run
}
const folderId = process.env.JOB_AGENT_FOLDER_ID;
if (!folderId) throw new Error("Set JOB_AGENT_FOLDER_ID in .env first (see .env.example).");
if (!process.env.JOB_AGENT_TOKEN) setEnv("JOB_AGENT_TOKEN", randomBytes(24).toString("base64url"));

const url = process.argv[2];
if (!url) {
  const script = readFileSync("apps-script/Code.gs", "utf8")
    .replace("__TOKEN__", process.env.JOB_AGENT_TOKEN!)
    .replace("__FOLDER_ID__", folderId);
  mkdirSync(".cache", { recursive: true });
  writeFileSync(".cache/Code.gs", script);
  try {
    execFileSync("pbcopy", { input: script });
    console.log("The script is on your clipboard (also saved to .cache/Code.gs).");
  } catch {
    console.log("Script saved to .cache/Code.gs.");
  }
  console.log(`
1. Open https://script.google.com and click "New project".
2. Select everything in the editor, paste, and save (Cmd+S).
3. Deploy > New deployment > gear icon > Web app.
   Execute as: Me. Who has access: Anyone. Click Deploy and allow access
   (Google warns the app is unverified: Advanced > Go to project, since it's your own script).
4. Copy the Web app URL and run:  npm run bridge -- <URL>`);
} else {
  if (!/^https:\/\/script\.google\.com\/macros\/s\/[\w-]+\/exec$/.test(url)) throw new Error("Expected a URL like https://script.google.com/macros/s/.../exec");
  setEnv("JOB_AGENT_SCRIPT_URL", url);
  const { listFolder, setupAgentFiles } = await import("./google.ts");
  const files = await listFolder(folderId);
  console.log(`Bridge works. The Job Application Agent folder has: ${files.map((f) => f.name).join(", ")}`);
  if (!process.env.JOB_AGENT_TRACKER_ID) {
    const own = await setupAgentFiles();
    setEnv("JOB_AGENT_TRACKER_ID", own.trackerId);
    setEnv("JOB_AGENT_APPLICATIONS_ID", own.applicationsId);
    console.log(`Created the agent's own files:\n  Application Tracker: ${own.trackerUrl}\n  Applications folder: ${own.applicationsUrl}`);
  }
}
