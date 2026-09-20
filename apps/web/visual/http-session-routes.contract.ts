import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import { ApiClient } from "../src/lib/api/client";
import { HttpAuthService } from "../src/features/auth/service";
import { HttpDirectoryService } from "../src/features/tasks/services/httpDirectoryService";
import { HttpTaskService } from "../src/features/tasks/services/httpTaskService";

const api = process.env.BT_HTTP_API_URL;
const web = process.env.BT_HTTP_WEB_URL;
test.skip(!api || !web, "Requires explicit owned API and web URLs; never uses a default stack.");

test("persistent session routes: real login, reload, new tab, URL filtering, history and logout", async ({ page, context }, testInfo) => {
  const client: ApiClient = new ApiClient(api!, { token: () => auth.token() });
  const auth = new HttpAuthService(client, api!);
  const tasks = new HttpTaskService(client);
  const directory = new HttpDirectoryService(client);
  const email = `routes-${randomUUID()}@example.test`, password = randomUUID();
  await auth.register(email, "Route Contract", password);
  const key = () => Array.from(randomUUID().replaceAll("-", "").slice(0, 5), c => String.fromCharCode(65 + parseInt(c, 16))).join("");
  const alpha = await directory.createProject({ name: `Alpha ${randomUUID()}`, key: key(), tone: "accent" });
  const beta = await directory.createProject({ name: `Beta ${randomUUID()}`, key: key(), tone: "muted" });
  const suffix = randomUUID();
  const match = await tasks.create({ title: `Route needle alpha ${suffix}`, project: alpha.id });
  await tasks.update(match.id, { prio: 1, assignee: auth.current().user!.id });
  const priorityMiss = await tasks.create({ title: `Route other alpha ${suffix}`, project: alpha.id });
  await tasks.update(priorityMiss.id, { prio: 3 });
  const projectMiss = await tasks.create({ title: `Route needle beta ${suffix}`, project: beta.id });
  await tasks.update(projectMiss.id, { prio: 1, due: "2020-01-01" });
  const destination = `/projects/${alpha.id}?priority=1&q=needle&sort=updated&view=board`;
  const traffic: object[] = [];
  page.on("response", response => {
    const url = new URL(response.url());
    if (url.origin === api && url.pathname === "/tasks") traffic.push({ path: url.pathname + url.search, status: response.status() });
  });
  const errors: string[] = [];
  page.on("console", msg => { if (["error", "warning"].includes(msg.type())) errors.push(msg.text()); });
  const signIn = async () => {
    await page.getByLabel("Email", { exact: true }).fill(email);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
  };
  // A temporary bootstrap outage must not masquerade as signed out, or render data.
  await page.route(`${api}/auth/session`, route => route.request().method() === "GET" ? route.abort("internetdisconnected") : route.continue());
  await page.goto(web + destination);
  await expect(page.getByRole("button", { name: "Retry session check" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Welcome back" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Board", exact: true })).toHaveCount(0);
  await page.unroute(`${api}/auth/session`);
  // This deliberately injected network failure is recorded separately, not a silent-console pass.
  const injectedOutageConsole = errors.splice(0);
  expect(injectedOutageConsole.length).toBeGreaterThan(0);
  expect(injectedOutageConsole.every(message => message.includes("ERR_INTERNET_DISCONNECTED"))).toBe(true);
  await page.getByRole("button", { name: "Retry session check" }).click();
  await expect(page).toHaveURL(`${web}/login?returnTo=${encodeURIComponent(destination)}`);
  await expect(page.getByRole("region", { name: "Board", exact: true })).toHaveCount(0);
  await signIn();
  await expect(page).toHaveURL(web + destination);
  const board = page.getByRole("region", { name: "Board", exact: true });
  await expect(board.getByRole("button", { name: match.title, exact: true })).toBeVisible();
  await expect(page.getByText(priorityMiss.title, { exact: true })).toHaveCount(0);
  await expect(page.getByText(projectMiss.title, { exact: true })).toHaveCount(0);
  await page.reload();
  await expect(board.getByRole("button", { name: match.title, exact: true })).toBeVisible();
  await expect(page).toHaveURL(web + destination);
  const tab = await context.newPage();
  await tab.goto(web + destination);
  await expect(tab.getByRole("button", { name: match.title, exact: true })).toBeVisible();
  for (const route of ["/login", "/register"]) {
    await page.goto(web + route);
    await expect(page).toHaveURL(web + "/tasks");
    await expect(page.getByRole("heading", { name: "Welcome back" })).toHaveCount(0);
  }
  await page.goto(web + destination);
  await page.getByRole("link", { name: /^All tasks/ }).click();
  await expect(page).toHaveURL(`${web}/tasks?priority=1&q=needle&sort=updated&view=board`);
  await expect(page.getByRole("button", { name: projectMiss.title, exact: true })).toBeVisible();
  await page.getByRole("link", { name: /^My tasks/ }).click();
  await expect(page).toHaveURL(`${web}/tasks/mine?priority=1&q=needle&sort=updated&view=board`);
  await expect(page.getByRole("button", { name: projectMiss.title, exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: /^Overdue/ }).click();
  await expect(page.getByRole("button", { name: projectMiss.title, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: match.title, exact: true })).toHaveCount(0);
  await page.goBack();
  await expect(page.getByRole("button", { name: match.title, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: projectMiss.title, exact: true })).toHaveCount(0);
  await page.goForward();
  await expect(page.getByRole("button", { name: projectMiss.title, exact: true })).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(web + destination);
  await expect(page.getByRole("button", { name: match.title, exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("mobile-session-route.png"), fullPage: true });
  // Server-cookie logout is also observed by the still-open second tab.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  await expect(tab.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  await page.goBack(); await page.reload();
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  await expect(page.getByRole("button", { name: match.title, exact: true })).toHaveCount(0);
  await page.goto(`${web}/login?returnTo=${encodeURIComponent("//evil.test/tasks")}`);
  await signIn();
  await expect(page).toHaveURL(web + "/tasks");
  // No token/flag storage. Cookies remain opaque to JavaScript.
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length, readableSession: document.cookie.includes("bt_session") }))).toEqual({ local: 0, session: 0, readableSession: false });
  await page.screenshot({ path: testInfo.outputPath("desktop-session-route.png"), fullPage: true });
  expect(errors).toEqual([]);
  await testInfo.attach("query-and-viewports", { body: JSON.stringify({ input: "Playwright automation", viewports: [{ width: 375, height: 812 }, { width: 1440, height: 900 }], injectedOutageConsole, traffic }), contentType: "application/json" });
});
