// One-time: prints a Google refresh token for .env / GitHub secrets. Run with: npm run auth:google
import { createServer } from "node:http";
import { google } from "googleapis";
import { env } from "./env.ts";
import { SCOPES } from "./google.ts";

const PORT = 53682;
const client = new google.auth.OAuth2(env("GOOGLE_CLIENT_ID"), env("GOOGLE_CLIENT_SECRET"), `http://127.0.0.1:${PORT}/callback`);
const url = client.generateAuthUrl({ access_type: "offline", prompt: "consent", scope: SCOPES });

const server = createServer(async (req, res) => {
  const code = new URL(req.url ?? "", `http://127.0.0.1:${PORT}`).searchParams.get("code");
  if (!code) return void res.end("Waiting for Google sign-in...");
  const { tokens } = await client.getToken(code);
  res.end("Done. You can close this tab and return to the terminal.");
  console.log(`\nGOOGLE_REFRESH_TOKEN=${tokens.refresh_token}\n\nAdd that line to .env (and as a GitHub secret).`);
  server.close();
});
server.listen(PORT, "127.0.0.1", () => console.log(`Open this URL and sign in as the Drive owner:\n\n${url}\n`));
