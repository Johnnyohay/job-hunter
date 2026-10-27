// Local, supervised applying: opens each "Approved" job in Chrome, pre-fills the form,
// and waits for you to review and click Submit yourself. Run with: npm run apply
import { mkdirSync, writeFileSync } from "node:fs";
import { createInterface } from "node:readline/promises";
import { chromium, type Page } from "playwright";
import { docText } from "./google.ts";
import { coverLetterFrom } from "./materials.ts";
import { loadProfile } from "./profile.ts";
import { field } from "./text.ts";
import { STATUS, readTracker, today, updateRow } from "./tracker.ts";

async function fill(page: Page, label: RegExp, value: string) {
  if (!value) return;
  const input = page.getByLabel(label).first();
  if (await input.count()) await input.fill(value).catch(() => {});
}

async function main() {
  const profile = await loadProfile();
  const approved = (await readTracker(profile.trackerId)).filter((r) => r.Status === STATUS.approved);
  if (!approved.length) {
    console.log(`Nothing to apply to. Set a row's Status to "${STATUS.approved}" in the Application Tracker first.`);
    return;
  }

  const fullName = field(profile.aboutMe, "Full legal name");
  const [first = "", ...rest] = (field(profile.aboutMe, "Preferred name") || fullName).split(/\s+/);
  const me = {
    first,
    last: rest.join(" ") || fullName.split(/\s+/).slice(1).join(" "),
    full: fullName,
    email: field(profile.aboutMe, "Email"),
    phone: field(profile.aboutMe, "Phone"),
    linkedin: profile.linkedinUrl,
    website: field(profile.preferences, "Portfolio"),
  };

  let cvPath = "";
  if (profile.cvPdf) {
    mkdirSync(".cache", { recursive: true });
    cvPath = ".cache/CV.pdf";
    writeFileSync(cvPath, profile.cvPdf);
  }

  const rl = createInterface({ input: process.stdin, output: process.stdout });
  const browser = await chromium.launch({ headless: false, channel: "chrome" });
  const context = await browser.newContext();

  for (const row of approved) {
    const url = row["Apply URL"] || row["Job URL"] || "";
    console.log(`\n${row.Company}: ${row.Title}\n${url}`);
    const page = await context.newPage();
    await page.goto(url, { waitUntil: "domcontentloaded" });

    const docId = row.Materials?.match(/\/d\/([\w-]+)/)?.[1];
    const coverLetter = docId ? coverLetterFrom(await docText(docId)) : "";

    await fill(page, /first name/i, me.first);
    await fill(page, /last name/i, me.last);
    await fill(page, /^(full )?name\b/i, me.full);
    await fill(page, /e-?mail/i, me.email);
    await fill(page, /phone/i, me.phone);
    await fill(page, /linkedin/i, me.linkedin);
    await fill(page, /website|portfolio/i, me.website);
    await fill(page, /cover letter/i, coverLetter);
    if (cvPath) await page.locator('input[type="file"]').first().setInputFiles(cvPath).catch(() => {});

    const answer = (await rl.question(
      "Check every field, answer the custom questions, and click Submit in the browser.\n" +
        "Then press Enter to mark it Applied, type s to mark Skipped, or q to stop: ",
    )).trim().toLowerCase();
    if (answer === "q") break;
    await updateRow(profile.trackerId, row.rowNumber, answer === "s"
      ? { Status: STATUS.skipped }
      : { Status: STATUS.applied, "Applied On": today() });
    await page.close();
  }

  rl.close();
  await browser.close();
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
});
