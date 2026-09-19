import type { Attachment } from "../../model/types";

export type LinkResult = { ok: true; attachment: Attachment } | { ok: false; error: string };

const INVALID: LinkResult = { ok: false, error: "Enter a web address, like https://example.com" };

/**
 * Turns what the user typed into a link attachment: named after the title, or after the
 * address itself, with the host as the secondary line. Only http and https are links here;
 * a bare "example.com/page" is read as https.
 */
export function linkAttachment(input: string, title: string): LinkResult {
  const text = input.trim();
  if (!text || /\s/.test(text)) return INVALID;

  const scheme = /^([a-z][a-z0-9+.-]*):\/\//i.exec(text)?.[1].toLowerCase();
  if (scheme && scheme !== "http" && scheme !== "https") return INVALID;

  let url: URL;
  try {
    url = new URL(scheme ? text : `https://${text}`);
  } catch {
    return INVALID;
  }
  if (!url.hostname.includes(".") && url.hostname !== "localhost") return INVALID;

  const host = url.host.replace(/^www\./, "");
  const path = url.pathname.replace(/\/+$/, "");
  return { ok: true, attachment: { kind: "link", name: title.trim() || `${host}${path}`, meta: host, url: url.href } };
}
