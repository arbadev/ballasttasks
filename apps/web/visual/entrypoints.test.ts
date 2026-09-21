// @vitest-environment node
import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";

/** Exercise the real Playwright config consumer, not source text. --list starts no servers
 * and executes no tests: even the valid-binding cases cannot contact these inert URLs. */
const DISCOVERY_TIMEOUT = 90_000;
function discover(config: string, values: Record<string, string | undefined>) {
  const env = { ...process.env, ...values };
  delete env.BT_DESIGN_DIR;
  const result = spawnSync(process.execPath, ["node_modules/@playwright/test/cli.js", "test", `--config=${config}`, "--list"], { env, encoding: "utf8", timeout: DISCOVERY_TIMEOUT });
  expect(result.error, `Playwright discovery did not complete: ${result.error?.message}`).toBeUndefined();
  expect(result.signal, `Playwright discovery was stopped by ${result.signal}`).toBeNull();
  return result;
}

describe("explicit validation bindings", () => {
  it.each([
    ["playwright.config.ts", "NEXT_PUBLIC_API_URL"],
    ["http-contract.config.ts", "BT_HTTP_API_URL"],
    ["http-contract.config.ts", "BT_HTTP_WEB_URL"],
  ])("%s refuses a missing %s before any test/server can run", (config, variable) => {
    const result = discover(config, { NEXT_PUBLIC_API_URL: "http://127.0.0.1:1", BT_HTTP_API_URL: "http://127.0.0.1:1", BT_HTTP_WEB_URL: "http://127.0.0.1:2", [variable]: undefined });
    expect(result.status).toBe(1);
    expect(result.stderr).toContain(`Set ${variable} to an explicitly owned`);
  }, DISCOVERY_TIMEOUT + 10_000);

  it.each(["playwright.config.ts", "http-contract.config.ts"])("%s discovers its suite with explicit configuration without starting services", config => {
    const result = discover(config, { NEXT_PUBLIC_API_URL: "http://127.0.0.1:1", BT_HTTP_API_URL: "http://127.0.0.1:1", BT_HTTP_WEB_URL: "http://127.0.0.1:2" });
    expect(result.status).toBe(0);
    expect(result.stdout).toContain("Total:");
  }, DISCOVERY_TIMEOUT + 10_000);
});
