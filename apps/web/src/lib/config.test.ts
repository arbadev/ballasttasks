import { describe, expect, it } from "vitest";
import { parseConfig } from "./config";

describe("parseConfig", () => {
  it("throws a clear message when NEXT_PUBLIC_API_URL is missing", () => {
    expect(() => parseConfig({})).toThrow(/NEXT_PUBLIC_API_URL/);
  });

  it("throws when NEXT_PUBLIC_API_URL is blank", () => {
    expect(() => parseConfig({ NEXT_PUBLIC_API_URL: "   " })).toThrow(/NEXT_PUBLIC_API_URL/);
  });

  it("throws when NEXT_PUBLIC_API_URL is not an http(s) URL", () => {
    expect(() => parseConfig({ NEXT_PUBLIC_API_URL: "not a url" })).toThrow(/NEXT_PUBLIC_API_URL/);
    expect(() => parseConfig({ NEXT_PUBLIC_API_URL: "ftp://example.com" })).toThrow(
      /NEXT_PUBLIC_API_URL/,
    );
  });

  it("returns the API URL when the value is valid", () => {
    expect(parseConfig({ NEXT_PUBLIC_API_URL: "http://localhost:8000" })).toEqual({
      apiUrl: "http://localhost:8000", serviceMode: "http",
    });
  });

  it("requires an explicit demo opt-in and rejects unknown service modes", () => {
    expect(parseConfig({ NEXT_PUBLIC_API_URL: "http://api.test", NEXT_PUBLIC_SERVICE_MODE: "demo" }).serviceMode).toBe("demo");
    expect(() => parseConfig({ NEXT_PUBLIC_API_URL: "http://api.test", NEXT_PUBLIC_SERVICE_MODE: "typo" })).toThrow(/SERVICE_MODE/);
  });

  it("strips a trailing slash so paths can be appended safely", () => {
    expect(parseConfig({ NEXT_PUBLIC_API_URL: "http://localhost:8000/" }).apiUrl).toBe(
      "http://localhost:8000",
    );
  });
});

describe("config", () => {
  it("is parsed from the environment when the module loads", async () => {
    const { config } = await import("./config");
    expect(config.apiUrl).toBe("http://localhost:8000");
  });
});
