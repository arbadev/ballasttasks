import { test as base } from "@playwright/test";

/** All contracts share the candidate's real IP-based credential budget (10/60s).
 * Give each bounded test a fresh natural window, including after a worker restart
 * or a previous invocation. Never reset counters, change limits, or retry a 429. */
export const test = base.extend<{ credentialWindow: void }>({
  credentialWindow: [async ({ browserName }, use) => {
    void browserName; // Built-in fixture dependency; no browser/network action here.
    await new Promise(resolve => setTimeout(resolve, 61_000));
    await use();
  }, { auto: true, timeout: 65_000 }],
});
export { expect } from "@playwright/test";
