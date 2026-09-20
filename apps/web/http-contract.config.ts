import { defineConfig } from "@playwright/test";

/** Real HTTP contracts, plus optional browser journeys when BT_HTTP_WEB_URL is explicit.
 * Never starts, reuses or modifies an application stack's configuration/lifecycle. */
export default defineConfig({
  testDir: "./visual",
  testMatch: "http-api.contract.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  outputDir: "visual-results/http-contract",
  reporter: [["list"]],
});
