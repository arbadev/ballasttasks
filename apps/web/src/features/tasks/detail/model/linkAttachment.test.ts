import { describe, expect, it } from "vitest";
import { linkAttachment } from "./linkAttachment";

describe("linkAttachment", () => {
  it("names a link after its title and keeps the host as the secondary line", () => {
    expect(linkAttachment("https://github.com/arbadev/ballasttasks/pull/9", "Detail panel PR")).toEqual({
      ok: true,
      attachment: { kind: "link", name: "Detail panel PR", meta: "github.com", url: "https://github.com/arbadev/ballasttasks/pull/9" },
    });
  });

  it("falls back to host and path when no title is given, without a trailing slash or www", () => {
    expect(linkAttachment("https://www.example.com/docs/ports/", "  ")).toEqual({
      ok: true,
      attachment: { kind: "link", name: "example.com/docs/ports", meta: "example.com", url: "https://www.example.com/docs/ports/" },
    });
    expect(linkAttachment("https://vectal.ai", "")).toMatchObject({ attachment: { name: "vectal.ai", meta: "vectal.ai" } });
  });

  it("accepts an address typed without a scheme", () => {
    expect(linkAttachment("localhost:8000/docs", "")).toMatchObject({ ok: true, attachment: { name: "localhost:8000/docs", meta: "localhost:8000" } });
    expect(linkAttachment("example.com", "")).toMatchObject({ ok: true });
  });

  it("keeps the query and the fragment of the address it was given", () => {
    expect(linkAttachment("https://example.com/docs?tab=ports#adapters", "")).toEqual({
      ok: true,
      attachment: { kind: "link", name: "example.com/docs", meta: "example.com", url: "https://example.com/docs?tab=ports#adapters" },
    });
  });

  it("rejects blanks, prose and schemes that are not the web", () => {
    const notTheWeb = ["mailto:someone@example.com", "mailto:1@example.com", "tel:+34600000000", "tel:600000000", "urn:isbn:0451450523", "javascript:x@evil.com"];
    for (const bad of ["", "   ", "not a link", "javascript:alert(1)", "ftp://files.example.com", "http://", "nodots", ...notTheWeb]) {
      expect(linkAttachment(bad, "x"), bad).toEqual({ ok: false, error: "Enter a web address, like https://example.com" });
    }
  });

  it("rejects an address carrying credentials, so none is ever stored on a task", () => {
    expect(linkAttachment("https://user:secret@example.com/docs", "x")).toEqual({ ok: false, error: "Enter a web address, like https://example.com" });
  });
});
