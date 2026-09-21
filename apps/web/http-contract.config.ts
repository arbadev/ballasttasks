import { defineConfig } from "@playwright/test";

for (const variable of ["BT_HTTP_API_URL", "BT_HTTP_WEB_URL"]) {
  if (!process.env[variable]) throw new Error(`Set ${variable} to an explicitly owned service before running HTTP contracts; no default endpoint is selected.`);
}

/** Real HTTP contracts, plus optional browser journeys when BT_HTTP_WEB_URL is explicit.
 * Never starts, reuses or modifies an application stack's configuration/lifecycle. */
export default defineConfig({
  testDir: "./visual",
  testMatch: /http-.*\.contract\.ts/,
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  outputDir: "visual-results/http-contract",
  reporter: [["list"]],
});
