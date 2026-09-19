import { defineConfig, devices } from "@playwright/test";

/**
 * Visual comparison of the app against the design snapshot (npm run test:visual).
 * The design is deliberately not in the repository: point BT_DESIGN_DIR at the folder that
 * holds "Ballast Tasks v2.dc.html" and its support.js. Without it the suite skips itself.
 */
const designDir = process.env.BT_DESIGN_DIR;

export const APP_URL = "http://127.0.0.1:47812";
export const DESIGN_URL = "http://127.0.0.1:47811";

export default defineConfig({
  testDir: "./visual",
  testMatch: /.*\.visual\.ts/,
  outputDir: "./visual-results/.playwright",
  // Baselines for the flows the design has no reference for (projects.visual.ts). One set for
  // every platform: they were recorded on macOS, so allow for font rasterisation elsewhere.
  snapshotPathTemplate: "{testDir}/__screenshots__/{testFileName}/{arg}{ext}",
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.01 } },
  reporter: [["list"]],
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  use: { ...devices["Desktop Chrome"], deviceScaleFactor: 1 },
  webServer: [
    {
      // The tasks UI is in-memory; the API URL only has to be well-formed.
      command: "node node_modules/next/dist/bin/next dev --port 47812 --hostname 127.0.0.1",
      url: APP_URL,
      env: { NEXT_PUBLIC_API_URL: "http://127.0.0.1:47899" },
      reuseExistingServer: true,
      timeout: 120_000,
    },
    ...(designDir
      ? [
          {
            command: "python3 -m http.server 47811 --bind 127.0.0.1",
            cwd: designDir,
            url: DESIGN_URL,
            reuseExistingServer: true,
            timeout: 30_000,
          },
        ]
      : []),
  ],
});
