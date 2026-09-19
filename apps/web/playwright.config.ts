import { defineConfig, devices } from "@playwright/test";

/**
 * Visual comparison of the app against the design snapshot (npm run test:visual).
 * The design is deliberately not in the repository: point BT_DESIGN_DIR at the folder that
 * holds "Ballast Tasks v2.dc.html" and its support.js. Without it the suite skips itself.
 */
const designDir = process.env.BT_DESIGN_DIR;

/**
 * Both servers are reused when already up, so two checkouts running the suite at once would
 * screenshot each other's app. Give each its own pair with BT_VISUAL_APP_PORT / BT_VISUAL_DESIGN_PORT.
 */
const appPort = Number(process.env.BT_VISUAL_APP_PORT ?? 47812);
const designPort = Number(process.env.BT_VISUAL_DESIGN_PORT ?? 47811);

export const APP_URL = `http://127.0.0.1:${appPort}`;
export const DESIGN_URL = `http://127.0.0.1:${designPort}`;

export default defineConfig({
  testDir: "./visual",
  testMatch: /.*\.visual\.ts/,
  outputDir: "./visual-results/.playwright",
  reporter: [["list"]],
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  use: { ...devices["Desktop Chrome"], deviceScaleFactor: 1 },
  webServer: [
    {
      // The tasks UI is in-memory; the API URL only has to be well-formed.
      command: `node node_modules/next/dist/bin/next dev --port ${appPort} --hostname 127.0.0.1`,
      url: APP_URL,
      env: { NEXT_PUBLIC_API_URL: "http://127.0.0.1:47899" },
      reuseExistingServer: true,
      timeout: 120_000,
    },
    ...(designDir
      ? [
          {
            command: `python3 -m http.server ${designPort} --bind 127.0.0.1`,
            cwd: designDir,
            url: DESIGN_URL,
            reuseExistingServer: true,
            timeout: 30_000,
          },
        ]
      : []),
  ],
});
