import { randomBytes, randomUUID } from "node:crypto";
import type { Page } from "@playwright/test";
import { expect, test } from "./http-fixtures";
import { ApiClient } from "../src/lib/api/client";
import { HttpAuthService } from "../src/features/auth/service";
import type { components } from "../src/lib/api/schema";

type Schemas = components["schemas"];
const api = process.env.BT_HTTP_API_URL;
const web = process.env.BT_HTTP_WEB_URL;
test.skip(!web, "Set BT_HTTP_WEB_URL to the explicitly owned served application.");

async function fixture() {
  const client: ApiClient = new ApiClient(api!, { token: () => auth.token() });
  const auth = new HttpAuthService(client, api!);
  const email = `continuity-${randomUUID()}@example.test`, password = randomUUID();
  await auth.register(email, "Route Continuity", password);
  const key = [...randomBytes(5)].map(value => String.fromCharCode(65 + value % 26)).join("");
  const project = await client.request<Schemas["ProjectResponse"]>("/projects", { method: "POST", body: { name: `Continuity ${key}`, key, color: null } });
  return { client, project, async login(page: Page, destination: string) {
    await page.goto(web + destination);
    await page.getByLabel("Email", { exact: true }).fill(email);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page).toHaveURL(web + destination);
  } };
}

test("served route continuity: pagination reload/history and project name-only PATCH", async ({ page }) => {
  const { client, project, login } = await fixture();
  for (let index = 0; index < 51; index++) {
    await client.request("/tasks", { method: "POST", body: { title: `Record ${index}`, project_id: project.id, importance: index } });
  }
  const route = `/projects/${project.id}?sort=importance`;
  await login(page, `${route}&offset=50`);
  const pages = page.getByRole("navigation", { name: "Task pages" });
  const last = page.getByRole("button", { name: "Record 0", exact: true });
  await expect(last).toBeVisible();
  await expect(pages).toContainText("51–51 of 51");
  await expect(page.getByRole("button", { name: "Record 50", exact: true })).toHaveCount(0);
  await page.reload();
  await expect(last).toBeVisible();
  await expect(page).toHaveURL(web + `${route}&offset=50`);
  await pages.getByRole("button", { name: "Previous page" }).click();
  await expect(page).toHaveURL(web + route);
  await expect(page.getByRole("button", { name: "Record 50", exact: true })).toBeVisible();
  await expect(last).toHaveCount(0);
  await page.goBack();
  await expect(last).toBeVisible();
  await expect(pages).toContainText("51–51 of 51");
  await page.getByText("Board", { exact: true }).click();
  await expect(page).toHaveURL(web + `${route}&view=board`);
  await expect(page.getByRole("button", { name: "Record 50", exact: true })).toBeVisible();
  const query = page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.origin === api && url.pathname === "/tasks" && url.searchParams.get("offset") === "50" && url.searchParams.get("project_id") === project.id && url.searchParams.get("status") === "all";
  });
  await pages.getByRole("button", { name: "Next page" }).click();
  expect((await query).status()).toBe(200);
  await expect(last).toBeVisible();
  await expect(page).toHaveURL(web + `${route}&view=board&offset=50`);
  await page.reload();
  await expect(last).toBeVisible();
  await expect(pages).toContainText("51–51 of 51 across all columns");
  await page.getByRole("button", { name: "Edit project", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Edit project", exact: true });
  const renamed = `${project.name} renamed`;
  await dialog.getByRole("textbox", { name: "Name", exact: true }).fill(renamed);
  const patch = page.waitForRequest(request => request.url() === `${api}/projects/${project.id}` && request.method() === "PATCH");
  await dialog.getByRole("button", { name: "Save changes" }).click();
  expect((await patch).postDataJSON()).toEqual({ name: renamed });
  await expect(dialog).toBeHidden();
  await expect(page.getByTestId("crumb")).toHaveText(renamed);
  await expect(page.getByRole("button", { name: "Edit project", exact: true })).toBeFocused();
  expect(await client.get(`/projects/${project.id}`)).toMatchObject({ name: renamed, key: project.key, color: null, open_tasks: 51 });
});

test("served route continuity: acknowledged step/comment readback recovery never repeats POST", async ({ page }) => {
  const { client, project, login } = await fixture();
  const task = await client.request<Schemas["TaskResponse"]>("/tasks", { method: "POST", body: { title: "Readback continuity", project_id: project.id } });
  await login(page, `/projects/${project.id}`);
  await page.getByRole("button", { name: task.title, exact: true }).click();
  const panel = page.getByRole("dialog", { name: task.title, exact: true });
  const detail = `${api}/tasks/${task.id}`;
  let refuseReadback = false;
  await page.route(detail, route => route.request().method() === "GET" && refuseReadback ? route.abort("internetdisconnected") : route.continue());
  for (const [kind, endpoint, label] of [["step", "steps", "Add a step"], ["comment", "comments", "Write a comment"]] as const) {
    const value = `Acknowledged ${kind}`;
    const writes: string[] = [];
    page.on("request", request => { if (request.url() === `${detail}/${endpoint}` && request.method() === "POST") writes.push(request.method()); });
    const input = panel.getByRole("textbox", { name: label, exact: true });
    await expect(input).toBeVisible();
    refuseReadback = true;
    await input.fill(value);
    await input.press("Enter");
    await expect(panel.getByRole("alert")).toContainText("was saved");
    await expect(panel.getByText("saved · reload needed", { exact: true })).toBeVisible();
    expect(writes).toEqual(["POST"]);
    await input.fill("Independent newer draft");
    refuseReadback = false;
    await panel.getByRole("button", { name: "Reload task", exact: true }).click();
    await expect(panel.getByRole("alert")).toHaveCount(0);
    await expect(input).toHaveValue("Independent newer draft");
    expect(writes).toEqual(["POST"]);
    if (kind === "step") await expect(panel.getByRole("button", { name: `Rename step: ${value}`, exact: true })).toBeVisible();
    else await expect(panel.getByText(value, { exact: true })).toBeVisible();
    await input.fill("");
  }
  const steps = await client.get<Schemas["StepListResponse"]>(`/tasks/${task.id}/steps`);
  expect(steps.items.map(step => step.title)).toEqual(["Acknowledged step"]);
  const activity = await client.get<Schemas["ActivityListResponse"]>(`/tasks/${task.id}/activity`);
  expect(activity.items.filter(entry => entry.kind === "comment").map(entry => entry.text)).toEqual(["Acknowledged comment"]);
});
