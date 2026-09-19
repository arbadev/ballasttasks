import { defineConfig } from "@playwright/test";

/** Node-only real HTTP contracts. Never starts, reuses or modifies an application stack. */
export default defineConfig({
  testDir: "./visual",
  testMatch: "http-api.contract.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  outputDir: "visual-results/http-contract",
  reporter: [["list"]],
});
