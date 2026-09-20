import { randomBytes, randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import { ApiClient, ApiError } from "../src/lib/api/client";
import type { components } from "../src/lib/api/schema";
import { HttpAuthService } from "../src/features/auth/service";
import { HttpDirectoryService } from "../src/features/tasks/services/httpDirectoryService";
import { HttpTaskService } from "../src/features/tasks/services/httpTaskService";
import { HttpStepGenerationService } from "../src/features/tasks/services/httpStepGenerationService";
import { DEFAULT_QUERY } from "../src/features/tasks/model/filter";
import { dayFrom } from "../src/features/tasks/model/due";

type Schemas = components["schemas"];
const base = process.env.BT_HTTP_API_URL;
test.skip(!base, "Set BT_HTTP_API_URL to a verified task-owned API; no default endpoint is contacted.");

function session(url: string) {
  const client: ApiClient = new ApiClient(url, { token: () => auth.token(), version: () => auth.current().epoch, unauthorized: () => auth.expire() });
  const auth = new HttpAuthService(client, url);
  return { client, auth, tasks: new HttpTaskService(client), directory: new HttpDirectoryService(client) };
}

test.describe("served query-backed board focus", () => {
  const web = process.env.BT_HTTP_WEB_URL;
  test.skip(!web, "Set BT_HTTP_WEB_URL to the same task-owned HTTP application's URL for browser contracts.");

  for (const focusOwner of ["retry", "unrelated input"] as const) {
    test(`authoritative target satisfaction preserves ${focusOwner} focus at the settled query boundary`, async ({ page }) => {
      expect(["127.0.0.1", "localhost"]).toContain(new URL(web!).hostname);
      const { auth, tasks } = session(base!);
      const email = `focus-${randomUUID()}@example.test`;
      const password = randomUUID();
      await auth.register(email, "Focus Contract", password);
      const task = await tasks.create({ title: `Focus boundary ${randomUUID()}` });
      try {
        await page.clock.install();
        await page.goto(web!);
        await page.getByRole("textbox", { name: "Email", exact: true }).fill(email);
        await page.getByRole("textbox", { name: "Password", exact: true }).fill(password);
        await page.getByRole("button", { name: "Sign in", exact: true }).click();
        const search = page.getByRole("searchbox", { name: "Search tasks" });
        await search.fill(task.title);
        await page.getByText("Board", { exact: true }).click();
        const board = page.getByRole("region", { name: "Board", exact: true });
        const card = board.getByRole("button", { name: task.title, exact: true });
        await expect(card).toBeVisible();
        await expect(board).toHaveAttribute("aria-busy", "false");
        // A genuine transport refusal, as with the native Offline keyboard move.
        const taskUrl = `${base}/tasks/${task.id}`;
        await page.route(taskUrl, (route) => route.request().method() === "PATCH" ? route.abort("internetdisconnected") : route.continue());
        await card.press("Shift+ArrowRight");
        const retry = board.getByRole("button", { name: `Retry moving "${task.title}"`, exact: true });
        await expect(retry).toBeVisible();
        await page.unroute(taskUrl);
        // Ordinary keyboard navigation establishes Retry ownership; it never activates Retry.
        for (let stops = 0; stops < 16 && !(await retry.evaluate((el) => el === document.activeElement)); stops++) {
          await page.keyboard.press("Shift+Tab");
        }
        await expect(retry).toBeFocused();
        if (focusOwner === "unrelated input") await search.click();
        const focus = focusOwner === "retry" ? retry : search;
        await expect(focus).toBeFocused();
        // Record DOM focus lifetime, not implementation state, to expose the first divergence.
        await page.evaluate(({ id, title }) => {
          const events: object[] = [];
          for (const type of ["focusin", "focusout"]) document.addEventListener(type, (event) => {
            const target = event.target as HTMLElement;
            const related = (event as FocusEvent).relatedTarget as HTMLElement | null;
            events.push({ type, tag: target.tagName, label: target.getAttribute("aria-label"), connected: target.isConnected, relatedTag: related?.tagName ?? null });
          }, true);
          const boundary = new Promise<{ cardFocused: boolean; searchFocused: boolean }>((resolve) => {
            const observer = new MutationObserver(() => {
              const card = document.querySelector(`[data-card-open="${id}"]`);
              const retry = [...document.querySelectorAll("button")].some((button) => button.getAttribute("aria-label") === `Retry moving "${title}"`);
              if (!card || card.closest("[data-column]")?.getAttribute("data-column") !== "progress" || retry || document.querySelector('[aria-label="Board"][aria-busy="true"]')) return;
              observer.disconnect();
              const result = { cardFocused: card === document.activeElement, searchFocused: document.activeElement === document.querySelector('[aria-label="Search tasks"]') };
              events.push({ type: "query-settled", focusTag: document.activeElement?.tagName, ...result });
              resolve(result);
            });
            observer.observe(document.body, { subtree: true, childList: true, attributes: true });
          });
          Object.assign(window, { boardFocusEvents: events, boardFocusBoundary: boundary });
        }, { id: task.id, title: task.title });
        // A separate authenticated client changes canonical status. The UI learns only through
        // its real minute-tick query, not a workspace command or injected React state.
        await tasks.move(task.id, "progress");
        const refreshed = page.waitForResponse((response) => response.url().startsWith(`${base}/tasks?`) && response.request().method() === "GET");
        await page.clock.fastForward(60_000);
        await refreshed;
        const boundary = await page.evaluate(() => (window as unknown as { boardFocusBoundary: Promise<{ cardFocused: boolean; searchFocused: boolean }> }).boardFocusBoundary);
        const moved = board.getByRole("region", { name: "In Progress", exact: true }).getByRole("button", { name: task.title, exact: true });
        await expect(moved).toBeVisible();
        await expect(retry).toHaveCount(0);
        await expect(board).toHaveAttribute("aria-busy", "false");
        console.log(JSON.stringify(await page.evaluate(() => ({
          focusOwnerTag: document.activeElement?.tagName,
          focusOwnerLabel: document.activeElement?.getAttribute("aria-label"),
          events: (window as unknown as { boardFocusEvents: object[] }).boardFocusEvents,
        }))));
        // Do not wait for focus to become correct: the independent query boundary settled.
        expect(focusOwner === "retry" ? boundary.cardFocused : boundary.searchFocused).toBe(true);
        expect((await tasks.get(task.id))?.status).toBe("progress");
      } finally {
        await tasks.remove(task.id);
        auth.logout();
      }
    });
  }
});

test("UTC quick-action date survives a fresh authenticated read without shifting entered dates or null", async () => {
  expect(["127.0.0.1", "localhost"]).toContain(new URL(base!).hostname);
  const { client, auth, tasks } = session(base!);
  const email = `utc-${randomUUID()}@example.test`;
  const password = randomUUID();
  await auth.register(email, "UTC Contract", password);
  const task = await tasks.create({ title: "UTC date persistence" });
  const tomorrow = dayFrom(1, Date.now()); // Actual test instant; no clock override or synchronization subsystem.
  await tasks.update(task.id, { due: tomorrow });
  const authoritative = await client.get<Schemas["TaskDetailResponse"]>(`/tasks/${task.id}`);
  expect(authoritative.due_date).toBe(tomorrow);
  expect(authoritative.attention.days_until_due).toBe(1);
  auth.logout();
  const fresh = session(base!);
  expect(fresh.auth.current().user).toBeNull();
  await fresh.auth.login(email, password);
  expect((await fresh.tasks.get(task.id))?.due).toBe(tomorrow);
  await fresh.tasks.update(task.id, { due: "2026-11-01" });
  expect((await fresh.tasks.get(task.id))?.due).toBe("2026-11-01");
  await fresh.tasks.update(task.id, { due: null });
  expect((await fresh.tasks.get(task.id))?.due).toBeNull();
  await fresh.tasks.remove(task.id);
  fresh.auth.logout();
  console.log(`PASS real UTC date helper/API contract: tomorrow=${tomorrow}, server distance=1, fresh-login persistence, unchanged entered day, exact-null Clear. Native detail quick-action UI remains a separate acceptance check.`);
});

test("real atomic ceiling rejection retains proposals and permits one reduced bulk acceptance", async () => {
  const { client, auth, tasks } = session(base!);
  expect(["127.0.0.1", "localhost"]).toContain(new URL(base!).hostname);
  expect((await client.get<Schemas["ReadinessResponse"]>("/health/ready")).ai.provider).toBe("fake");
  await auth.register(`ceiling-${randomUUID()}@example.test`, "Ceiling Contract", randomUUID());
  const task = await tasks.create({ title: "Atomic ceiling" });
  // Existing fixture steps respect the API's separate 20-title per-request limit.
  for (let offset = 0; offset < 98; offset += 20) {
    await tasks.acceptSteps(task.id, Array.from({ length: Math.min(20, 98 - offset) }, (_, i) => `Existing ${offset + i}`));
  }
  const generation = new HttpStepGenerationService(client, tasks, () => Date.now());
  const stop = generation.subscribe(() => {});
  try {
    await generation.start(task.id);
    await expect.poll(() => generation.current()?.phase, { timeout: 30_000 }).toBe("proposed");
    await expect(generation.accept()).rejects.toMatchObject({ status: 422 });
    expect((await tasks.get(task.id))?.steps).toHaveLength(98);
    const proposal = generation.current();
    expect(proposal?.phase).toBe("proposed");
    if (proposal?.phase !== "proposed") throw new Error("Rejected proposal was not retained");
    expect(proposal.steps).toHaveLength(3);
    generation.removeProposed(proposal.steps[0].id);
    expect((await generation.accept())?.steps).toHaveLength(100);
    expect(await generation.accept()).toBeNull();
    expect((await tasks.get(task.id))?.steps).toHaveLength(100);
    await tasks.remove(task.id);
  } finally { stop(); generation.dispose(); auth.logout(); }
  console.log("PASS real atomic ceiling: 98 + 3 rejected unchanged; 98 + 2 accepted once as 100. Provider=fake; credentials omitted.");
});

test("real bearer HTTP, PostgreSQL persistence, server queries, attachments and real queued proposals", async () => {
  const url = new URL(base!);
  expect(["127.0.0.1", "localhost"]).toContain(url.hostname);
  expect(url.port).not.toBe("8000");
  const { client, auth, tasks, directory } = session(base!);
  const health = await client.get<Schemas["ReadinessResponse"]>("/health/ready");
  expect(health.status).toBe("ready");
  expect(health.ai.provider).toBe("fake");
  const email = `contract-${randomUUID()}@example.test`;
  const password = randomUUID();
  await auth.register(email, "HTTP Contract", password);
  const caller = await directory.currentUser();
  const key = [...randomBytes(5)].map((value) => String.fromCharCode(65 + value % 26)).join("");
  const project = await directory.createProject({ name: `Contract ${key}`, key, tone: "accent" });
  // Fixtures are ordinary authenticated API writes, not a database bypass or dependency override.
  for (let index = 0; index < 51; index++) {
    await client.request("/tasks", { method: "POST", body: { title: `needle ${String(index).padStart(2, "0")}`, project_id: project.id, importance: index, status: index === 50 ? "done" : "todo", assignee_id: caller.id } });
  }
  const query = { ...DEFAULT_QUERY, project: project.id, status: "all" as const, search: "needle" };
  const first = await tasks.query({ query, sort: "importance", board: false, offset: 0 });
  const second = await tasks.query({ query, sort: "importance", board: false, offset: 50 });
  expect(first.total).toBe(51);
  expect(first.tasks).toHaveLength(50);
  expect(second.tasks).toHaveLength(1);
  expect(new Set([...first.tasks, ...second.tasks].map((task) => task.id)).size).toBe(51);
  expect(first.tasks[0].importance).toBe(50);
  expect(second.tasks[0].importance).toBe(0);
  expect(first.sidebar.byProject[project.id]).toBe(50);
  const matching = await tasks.query({ query: { ...query, search: "needle 00", scope: "mine" }, sort: "updated", board: false, offset: 0 });
  expect(matching.total).toBe(1);
  expect(matching.tasks[0].title).toBe("needle 00");
  const board = await tasks.query({ query: { ...query, status: "testing" }, sort: "importance", board: true, offset: 0 });
  expect(board.total).toBe(51);
  expect(board.headerTotal).toBe(0);
  expect(board.columns).toEqual({ todo: 50, progress: 0, testing: 0, done: 1 });

  let task = await tasks.create({ title: "Persistent integration", project: project.id });
  expect(task.key).toMatch(new RegExp(`^${key}-`));
  task = await tasks.update(task.id, { description: "Stored through HTTP", assignee: caller.id, due: "2026-12-01", prio: 1 });
  task = await tasks.update(task.id, { due: null });
  expect(task.due).toBeNull();
  expect(task.activity.some((entry) => entry.text === "Due date cleared")).toBe(true);
  task = await tasks.move(task.id, "progress");
  task = await tasks.addStep(task.id, "Manual step");
  task = await tasks.toggleStep(task.id, task.steps[0].id);
  expect(task.steps[0].done).toBe(true);
  task = await tasks.addComment(task.id, "A durable comment");
  task = await tasks.addAttachment(task.id, { kind: "link", name: "Docs", meta: "example.test", url: "https://example.test/docs" });
  task = await tasks.uploadAttachment(task.id, new File(["%PDF-1.4\nTask-owned fixture\n%%EOF"], "fixture.pdf", { type: "application/pdf" }));
  const file = task.attachments.find((attachment) => attachment.kind === "pdf")!;
  expect(await (await tasks.downloadAttachment(task.id, file.id!)).text()).toContain("Task-owned fixture");
  expect(file.url).toBeUndefined();

  const generation = new HttpStepGenerationService(client, tasks, () => Date.now());
  const stop = generation.subscribe(() => {});
  try {
    await generation.start(task.id);
    await expect.poll(() => generation.current()?.phase, { timeout: 30_000 }).toBe("proposed");
    expect((await tasks.get(task.id))?.steps).toHaveLength(1);
    const accepted = await generation.accept();
    expect(accepted?.steps).toHaveLength(4);
    expect(accepted?.activity.some((entry) => entry.text.startsWith("Drafted 3 steps"))).toBe(true);
  } finally { stop(); generation.dispose(); }

  auth.logout();
  const fresh = session(base!);
  expect(fresh.auth.current().user).toBeNull();
  await fresh.auth.login(email, password);
  const restored = await fresh.tasks.get(task.id);
  expect(restored).toMatchObject({ description: "Stored through HTTP", assignee: caller.id, due: null, status: "progress", key: task.key });
  expect(restored?.steps).toHaveLength(4);
  expect(restored?.attachments).toHaveLength(2);
  expect(restored?.activity.some((entry) => entry.text === "A durable comment")).toBe(true);
  await fresh.tasks.remove(task.id);
  expect(await fresh.tasks.get(task.id)).toBeNull();
  await expect(fresh.tasks.move(task.id, "done")).rejects.toThrow(/does not exist/);
  await expect(new ApiClient(base!).get(`/tasks/${first.tasks[0].id}`)).rejects.toBeInstanceOf(ApiError);
  fresh.auth.logout();
  console.log(`PASS real HTTP: project ${project.id}, 51 rows across two pages, shared counts, mutations/storage, real worker proposals/atomic acceptance, fresh-login persistence, deletion and unauthenticated rejection. Provider=fake; credentials omitted.`);
});
