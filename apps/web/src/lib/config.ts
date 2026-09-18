export interface AppConfig {
  apiUrl: string;
}

type Env = Partial<Record<"NEXT_PUBLIC_API_URL", string | undefined>>;

/** Pure validation, kept separate from the environment read so it can be tested directly. */
export function parseConfig(env: Env): AppConfig {
  const raw = env.NEXT_PUBLIC_API_URL?.trim();
  if (!raw) {
    throw new Error(
      "NEXT_PUBLIC_API_URL is not set. Define it in the environment (e.g. http://localhost:8000).",
    );
  }

  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`NEXT_PUBLIC_API_URL is not a valid URL: "${raw}".`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`NEXT_PUBLIC_API_URL must use http or https, got "${url.protocol}".`);
  }

  return { apiUrl: raw.replace(/\/+$/, "") };
}

// The only environment read in the app. Next.js inlines NEXT_PUBLIC_* values at build time
// only when the variable is referenced by its full literal name, so it cannot be looked up
// dynamically or destructured from process.env.
export const config: AppConfig = parseConfig({
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
});
