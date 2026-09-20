import type { Attachment } from "../../model/types";

export type LinkResult = { ok: true; attachment: Attachment } | { ok: false; error: string };

const INVALID: LinkResult = { ok: false, error: "Enter a web address, like https://example.com" };

/** Longer than any address a browser will follow, so a stray paste never reaches the store. */
const MAX_LENGTH = 2000;

function parse(text: string): URL | null {
  try {
    return new URL(text);
  } catch {
    return null;
  }
}

/**
 * Turns what the user typed into a link attachment: named after the title, or after the
 * address itself, with the host as the secondary line. Only http and https are links here;
 * a bare "example.com/page" is read as https. What makes "mailto:someone@example.com" a
 * non-link is the credentials it parses into, not its scheme.
 */
export function linkAttachment(input: string, title: string): LinkResult {
  const text = input.trim();
  if (!text || text.length > MAX_LENGTH || /\s/.test(text)) return INVALID;

  let url = parse(text);
  if (!url || (url.protocol !== "http:" && url.protocol !== "https:")) {
    url = text.includes("://") ? null : parse(`https://${text}`);
  }
  if (!url || url.username || url.password) return INVALID;
  if (!url.hostname.includes(".") && url.hostname !== "localhost") return INVALID;

  const host = url.host.replace(/^www\./, "");
  const path = url.pathname.replace(/\/+$/, "");
  return { ok: true, attachment: { kind: "link", name: title.trim() || `${host}${path}`, meta: host, url: url.href } };
}
