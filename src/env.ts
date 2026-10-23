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

/** Working files shared between the npm scripts and the Claude Code steps (gitignored). */
export const STATE = ".state";
