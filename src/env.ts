// Loads .env locally; in GitHub Actions the variables come from repository secrets.
try {
  process.loadEnvFile(".env");
} catch {
  // no .env file: rely on the real environment
}

export function env(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing environment variable ${name} (see .env.example)`);
  return value;
}

export const MODEL = "claude-opus-5-5";
