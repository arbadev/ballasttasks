import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { Providers } from "@/app/providers";
import { ApiClient } from "@/lib/api/client";
import { apiPerson, apiTask } from "@/test/httpFixtures";
import { FakeDirectoryService, FakeStepGenerationService, FakeTaskService } from "@/test/fakeServices";
import { server } from "@/test/server";
import { makeTask, NOW } from "@/test/tasks";
import type { Task } from "../model/types";
import { HttpTaskService } from "../services/httpTaskService";
import type { TaskPage } from "../services/query";
import { TaskReadbackError } from "../services/types";
import { WorkspaceProvider, useWorkspace } from "../workspace/WorkspaceProvider";
import { DetailSessionProvider, useComposer, useDetailSession } from "./DetailSession";
import { TaskDetail } from "./TaskDetail";

const base = "http://write-readback.test";
type Kind = "comment" | "step";
type Read = "detail" | "activity";
type Row = { id: string; text: string };

const AT = "2026-09-19T00:00:00Z";
const SUMMARY_UPDATED = Date.parse(AT);

const stepRow = (row: Row, position: number) => ({ id: row.id, task_id: "task-id", title: row.text, done: false, position, created_at: AT });
const commentRow = (row: Row) => ({ id: row.id, task_id: "task-id", kind: "comment", actor: apiPerson, text: row.text, created_at: AT });

/**
 * The footer's own text, asserted whole: "saved · reload needed" is not the settled "saved · <time>",
 * and neither is "saving…", "reloading…" or "not saved".
 */
const saveState = () => screen.getByTestId("save-state").textContent ?? "";
const SETTLED_SAVED = /^saved · (?!reload needed)\S/;

function setup(kind: Kind, failingRead: Read = "detail", rejectPost = false, client = new ApiClient(base)) {
  const stored: Row[] = [];
  const posts: string[] = [];
  const reads: Read[] = [];
  let readFailures = 1;
  let postRefused = false;
  let deleted = false;
  const failRead = (read: Read) => stored.length > 0 && failingRead === read && readFailures-- > 0;
  server.use(
    http.post(`${base}/tasks/task-id/${kind === "comment" ? "comments" : "steps"}`, async ({ request }) => {
      const body = await request.json() as { text?: string; title?: string };
      const text = (body.text ?? body.title)!;
      posts.push(text);
      if (rejectPost && !postRefused) {
        postRefused = true;
        readFailures = 0;
        return HttpResponse.json({ detail: "Refused before writing" }, { status: 422 });
      }
      const row: Row = { id: `${kind === "comment" ? "c" : "s"}${stored.length}`, text };
      stored.push(row);
      return HttpResponse.json(kind === "comment" ? commentRow(row) : stepRow(row, stored.length - 1), { status: 201 });
    }),
    http.get(`${base}/tasks/task-id`, () => {
      reads.push("detail");
      if (deleted) return HttpResponse.json({ detail: "Not found" }, { status: 404 });
      if (failRead("detail")) return HttpResponse.json({ detail: "Read unavailable" }, { status: 503 });
      return HttpResponse.json(apiTask({
        steps: kind === "step" ? stored.map(stepRow) : [],
        steps_total: kind === "step" ? stored.length : 0,
        comments_count: kind === "comment" ? stored.length : 0,
      }));
    }),
    http.patch(`${base}/tasks/task-id`, () => HttpResponse.json(apiTask())),
    http.get(`${base}/tasks/task-id/activity`, () => {
      reads.push("activity");
      if (failRead("activity")) return HttpResponse.json({ detail: "Activity unavailable" }, { status: 503 });
      const items = kind === "comment" ? stored.map(commentRow) : [];
      return HttpResponse.json({ items, total: items.length, limit: 200, offset: 0 });
    }),
  );
  const service = new HttpTaskService(client);
  const send = (text: string) => kind === "comment" ? service.addComment("task-id", text) : service.addStep("task-id", text);
  return {
    service, send, posts, reads, stored,
    texts: () => stored.map((row) => row.text),
    failAgain: () => { readFailures = 1; },
    deleteTask: () => { deleted = true; },
  };
}

/** A task as the panel holds it once its own detail has been read back. */
const canonical = (overrides: Partial<Task> = {}): Task => makeTask({ id: "task-id", detailLoaded: true, ...overrides });
const shows = (kind: Kind, id: string, text: string): Partial<Task> =>
  kind === "comment" ? { activity: [{ id, type: "comment", who: "ab", text, at: NOW }] } : { steps: [{ id, text, done: false }] };

// Carried from the scout: actual HTTP adapter/client and composer, not a mocked send.
describe("acknowledged composer write with failed readback", () => {
  it.each(["comment", "step"] as const)("recovers the acknowledged %s without a second POST", async (kind) => {
    const { service, send, texts, posts } = setup(kind);
    const { result } = renderHook(
      ({ task }: { task: Task }) => useComposer(task, kind, send, () => service.get("task-id")),
      { wrapper: DetailSessionProvider, initialProps: { task: canonical() } },
    );
    act(() => result.current.setText("Accepted once"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.failed).toBe("Accepted once"));
    expect(texts()).toEqual(["Accepted once"]);
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(posts).toEqual(["Accepted once"]);
    expect(texts()).toEqual(["Accepted once"]);
    expect(result.current.text).toBe("");
  });

  it("retains genuine POST refusal recovery", async () => {
    const { service, send, texts, posts } = setup("comment", "detail", true);
    const { result } = renderHook(
      ({ task }: { task: Task }) => useComposer(task, "comment", send, () => service.get("task-id")),
      { wrapper: DetailSessionProvider, initialProps: { task: canonical() } },
    );
    act(() => result.current.setText("Refused once"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.failed).toBe("Refused once"));
    expect(texts()).toEqual([]);
    expect(result.current.text).toBe("Refused once");
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(posts).toEqual(["Refused once", "Refused once"]);
    expect(texts()).toEqual(["Refused once"]);
    expect(result.current.text).toBe("");
  });
});

describe("readback recovery boundaries", () => {
  it("does not restore already-saved text after a genuine refusal was retried", async () => {
    const { service, send, texts, posts, failAgain } = setup("comment", "detail", true);
    const { result } = renderHook(
      ({ task }: { task: Task }) => useComposer(task, "comment", send, () => service.refresh("task-id")),
      { wrapper: DetailSessionProvider, initialProps: { task: canonical() } },
    );
    act(() => result.current.setText("Refused then saved"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.failed).toBe("Refused then saved"));
    expect(result.current.text).toBe("Refused then saved");
    failAgain();
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.refreshRequired).toBe(true));
    expect(result.current.text).toBe("");
    act(() => result.current.dismiss());
    act(() => result.current.submit());
    expect(result.current.busy).toBe(true);
    expect(posts).toHaveLength(2); // One refusal, one acknowledged write, never a third send.
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(texts()).toEqual(["Refused then saved"]);
    expect(posts).toHaveLength(2);
  });

  it("retains an independently retyped identical draft after read recovery", async () => {
    const { service, send, posts } = setup("step");
    const { result } = renderHook(
      ({ task }: { task: Task }) => useComposer(task, "step", send, () => service.refresh("task-id")),
      { wrapper: DetailSessionProvider, initialProps: { task: canonical() } },
    );
    act(() => result.current.setText("Same text, independent draft"));
    act(() => result.current.submit());
    act(() => result.current.setText("Same text, independent draft"));
    await waitFor(() => expect(result.current.refreshRequired).toBe(true));
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(result.current.text).toBe("Same text, independent draft");
    expect(posts).toHaveLength(1);
  });

  it("fences an obsolete session before read recovery can send anything", async () => {
    let epoch = 1;
    const client = new ApiClient(base, { token: () => "test-session", version: () => epoch, expectedVersion: 1 });
    const { service, send, reads, posts } = setup("comment", "detail", false, client);
    await expect(send("Saved before sign-out")).rejects.toBeInstanceOf(TaskReadbackError);
    epoch += 1;
    await expect(service.refresh("task-id")).rejects.toMatchObject({ kind: "session" });
    expect(reads).toEqual(["detail"]);
    expect(posts).toEqual(["Saved before sign-out"]);
  });

  it("never labels a rejected POST or a blank no-op as an acknowledged write", async () => {
    const { send, service, texts } = setup("comment", "detail", true);
    await expect(send("Refused")).rejects.toMatchObject({ status: 422 });
    expect(texts()).toEqual([]);
    server.use(http.get(`${base}/tasks/task-id`, () => HttpResponse.json({}, { status: 503 })));
    await expect(service.addComment("task-id", " ")).rejects.toMatchObject({ status: 503 });
  });

  it.each(["comment", "step"] as const)("names the stored %s row on the readback error", async (kind) => {
    const { send, stored } = setup(kind);
    const error = await send("Accepted once").catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(TaskReadbackError);
    expect((error as TaskReadbackError).saved).toEqual({ taskId: "task-id", kind, childId: stored[0].id });
  });
});

describe("what a canonical detail has to show before a recovery settles", () => {
  const holdAcknowledged = async (kind: Kind) => {
    const fixture = setup(kind);
    const view = renderHook(
      ({ task }: { task: Task }) => useComposer(task, kind, fixture.send, () => fixture.service.refresh("task-id")),
      { wrapper: DetailSessionProvider, initialProps: { task: canonical() } },
    );
    act(() => view.result.current.setText("Accepted once"));
    act(() => view.result.current.submit());
    await waitFor(() => expect(view.result.current.refreshRequired).toBe(true));
    return { ...fixture, ...view, storedId: fixture.stored[0].id };
  };

  it.each(["comment", "step"] as const)("settles once the task's own detail shows the stored %s row", async (kind) => {
    const { result, rerender, storedId, posts } = await holdAcknowledged(kind);
    rerender({ task: canonical(shows(kind, storedId, "Accepted once")) });
    await waitFor(() => expect(result.current.refreshRequired).toBe(false));
    expect(result.current.busy).toBe(false);
    expect(posts).toEqual(["Accepted once"]);
  });

  it("does not settle on another row that happens to carry the same text", async () => {
    const { result, rerender } = await holdAcknowledged("comment");
    rerender({ task: canonical(shows("comment", "someone-elses-row", "Accepted once")) });
    await act(async () => {});
    expect(result.current.refreshRequired).toBe(true);
    expect(result.current.busy).toBe(true);
  });

  it("does not settle on a list summary that carries the stored row", async () => {
    const { result, rerender, storedId } = await holdAcknowledged("comment");
    rerender({ task: canonical({ detailLoaded: false, ...shows("comment", storedId, "Accepted once") }) });
    await act(async () => {});
    expect(result.current.refreshRequired).toBe(true);
  });

  it("does not settle a genuine refusal, whatever the task shows", async () => {
    const { service, send } = setup("comment", "detail", true);
    const { result, rerender } = renderHook(
      ({ task }: { task: Task }) => useComposer(task, "comment", send, () => service.refresh("task-id")),
      { wrapper: DetailSessionProvider, initialProps: { task: canonical() } },
    );
    act(() => result.current.setText("Refused once"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.failed).toBe("Refused once"));
    rerender({ task: canonical(shows("comment", "c0", "Refused once")) });
    await act(async () => {});
    expect(result.current.failed).toBe("Refused once");
    expect(result.current.refreshRequired).toBe(false);
  });

  it("settles only the box whose own task shows the row", async () => {
    const { service, send } = setup("comment");
    const { result, rerender } = renderHook(
      ({ task, other }: { task: Task; other: Task }) => ({
        held: useComposer(task, "comment", send, () => service.refresh("task-id")),
        sibling: useComposer(other, "comment", send, () => service.refresh("other-task")),
      }),
      {
        wrapper: DetailSessionProvider,
        initialProps: { task: canonical(), other: makeTask({ id: "other-task", detailLoaded: true }) },
      },
    );
    act(() => result.current.held.setText("Accepted once"));
    act(() => result.current.held.submit());
    await waitFor(() => expect(result.current.held.refreshRequired).toBe(true));
    // Another task showing a row with the same id says nothing about this one.
    rerender({ task: canonical(), other: makeTask({ id: "other-task", detailLoaded: true, ...shows("comment", "c0", "Accepted once") }) });
    await act(async () => {});
    expect(result.current.held.refreshRequired).toBe(true);
    expect(result.current.held.busy).toBe(true);
  });
});

function Openers() {
  const { actions } = useWorkspace();
  return <>
    <button onClick={() => actions.selectTask("task-id")}>Open task</button>
    <button onClick={actions.reload}>Refresh list</button>
  </>;
}

async function renderPanel(kind: Kind, read: Read) {
  const fixture = setup(kind, read);
  const service = Object.assign(new FakeTaskService([makeTask({ id: "task-id", title: "Readback task" })]), {
    get: fixture.service.get.bind(fixture.service),
    update: fixture.service.update.bind(fixture.service),
    addComment: fixture.service.addComment.bind(fixture.service),
    addStep: fixture.service.addStep.bind(fixture.service),
  });
  render(<Providers taskService={service} directoryService={new FakeDirectoryService()} stepGenerationService={new FakeStepGenerationService()} clock={() => NOW}>
    <WorkspaceProvider><Openers /><TaskDetail /></WorkspaceProvider>
  </Providers>);
  await act(async () => {});
  fireEvent.click(screen.getByRole("button", { name: "Open task" }));
  const section = () => within(screen.getByRole("region", { name: kind === "comment" ? "Activity" : "Steps" }));
  const box = () => section().getByRole("textbox", { name: kind === "comment" ? "Write a comment" : "Add a step" });
  fireEvent.change(box(), { target: { value: "Accepted once" } });
  fireEvent.keyDown(box(), { key: "Enter" });
  // A different draft belongs to the user even while the first write/read is out.
  fireEvent.change(box(), { target: { value: "Independent next draft" } });
  return { ...fixture, section, box };
}

describe("visible acknowledged-write recovery", () => {
  it.each([
    ["comment", "detail"], ["comment", "activity"], ["step", "detail"], ["step", "activity"],
  ] as const)("%s's failed %s read offers read-only recovery and renders canonical content", async (kind, read) => {
    const { posts, texts, section, box, failAgain } = await renderPanel(kind, read);
    expect(await section().findByRole("alert")).toHaveTextContent(/was saved/i);
    expect(section().queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    await waitFor(() => expect(saveState()).toBe("saved · reload needed"));
    expect(box()).toHaveValue("Independent next draft");
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(posts).toEqual(["Accepted once"]);
    // Closing/reopening keeps the acknowledged recovery, not a new send.
    fireEvent.click(screen.getByRole("button", { name: "Close task" }));
    fireEvent.click(screen.getByRole("button", { name: "Open task" }));
    expect(box()).toHaveValue("Independent next draft");
    failAgain();
    fireEvent.click(section().getByRole("button", { name: "Reload task" }));
    expect(await section().findByRole("alert")).toHaveTextContent(/was saved/i);
    expect(posts).toEqual(["Accepted once"]);
    fireEvent.click(section().getByRole("button", { name: "Reload task" }));
    expect(await section().findByText("Accepted once")).toBeVisible();
    await waitFor(() => expect(section().queryByRole("alert")).not.toBeInTheDocument());
    expect(box()).toHaveValue("Independent next draft");
    expect(texts()).toEqual(["Accepted once"]);
    expect(posts).toEqual(["Accepted once"]);
    expect(saveState()).toMatch(SETTLED_SAVED);
  });

  it("forgets a deleted task on read recovery without repeating its acknowledged comment", async () => {
    const { deleteTask, posts, section } = await renderPanel("comment", "detail");
    await section().findByRole("alert");
    deleteTask();
    fireEvent.click(section().getByRole("button", { name: "Reload task" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts).toEqual(["Accepted once"]);
  });
});

describe("acknowledged recovery settled by a canonical reload from elsewhere", () => {
  it.each(["comment", "step"] as const)("a sibling save that reloads the task canonically settles the %s recovery", async (kind) => {
    const { posts, texts, section, box } = await renderPanel(kind, "detail");
    expect(await section().findByRole("alert")).toHaveTextContent(/was saved/i);
    fireEvent.change(screen.getByLabelText("Priority"), { target: { value: "0" } });
    expect(await section().findByText("Accepted once")).toBeVisible();
    await waitFor(() => expect(section().queryByRole("alert")).not.toBeInTheDocument());
    expect(box()).toHaveValue("Independent next draft");
    expect(posts).toEqual(["Accepted once"]);
    expect(texts()).toEqual(["Accepted once"]);
    expect(saveState()).toMatch(SETTLED_SAVED);
    // The box is the user's again: Enter sends the newer draft, and never the settled text.
    fireEvent.keyDown(box(), { key: "Enter" });
    await waitFor(() => expect(posts).toEqual(["Accepted once", "Independent next draft"]));
  });

  it("keeps the acknowledged recovery when the sibling save is refused", async () => {
    const { posts, section, box } = await renderPanel("comment", "detail");
    expect(await section().findByRole("alert")).toHaveTextContent(/was saved/i);
    server.use(http.patch(`${base}/tasks/task-id`, () => HttpResponse.json({ detail: "Refused" }, { status: 500 })));
    fireEvent.change(screen.getByLabelText("Priority"), { target: { value: "0" } });
    expect(await screen.findByText("Could not save the priority.")).toBeVisible();
    expect(section().getByRole("alert")).toHaveTextContent(/was saved/i);
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(posts).toEqual(["Accepted once"]);
  });
});

/** The workspace's own detail reload: nothing in the panel asked for it and no save tracked it. */
async function renderStaleReloadPanel(kind: Kind) {
  const fixture = setup(kind, "detail");
  let updatedAt = SUMMARY_UPDATED;
  const service = Object.assign(new FakeTaskService([]), {
    get: fixture.service.get.bind(fixture.service),
    addComment: fixture.service.addComment.bind(fixture.service),
    addStep: fixture.service.addStep.bind(fixture.service),
    query: async (): Promise<TaskPage> => ({
      tasks: [makeTask({ id: "task-id", title: "Readback task", detailLoaded: false, updatedAt })],
      total: 1, headerTotal: 1, limit: 50, offset: 0,
      sidebar: { all: 1, mine: 0, overdue: 0, byProject: {} },
      signals: { overdue: 0, critical: 0, soon: 0, unassigned: 0 },
    }),
  });
  render(<Providers taskService={service} directoryService={new FakeDirectoryService()} stepGenerationService={new FakeStepGenerationService()} clock={() => NOW}>
    <WorkspaceProvider><Openers /><TaskDetail /></WorkspaceProvider>
  </Providers>);
  await act(async () => {});
  fireEvent.click(screen.getByRole("button", { name: "Open task" }));
  const label = kind === "comment" ? "Activity" : "Steps";
  await screen.findByRole("region", { name: label });
  const section = () => within(screen.getByRole("region", { name: label }));
  const box = () => section().getByRole("textbox", { name: kind === "comment" ? "Write a comment" : "Add a step" });
  return { ...fixture, section, box, bumpSummary: () => { updatedAt += 1000; } };
}

describe("a reload the panel never asked for", () => {
  it.each(["comment", "step"] as const)("settles the acknowledged %s once the workspace's own detail reload shows it", async (kind) => {
    const { box, section, bumpSummary, posts, reads } = await renderStaleReloadPanel(kind);
    fireEvent.change(box(), { target: { value: "Accepted once" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(await section().findByRole("alert")).toHaveTextContent(/was saved/i);
    await waitFor(() => expect(saveState()).toBe("saved · reload needed"));
    const before = reads.length;
    // The refreshed summary is newer, so the workspace reloads this task's detail by itself.
    bumpSummary();
    fireEvent.click(screen.getByRole("button", { name: "Refresh list" }));
    expect(await section().findByText("Accepted once")).toBeVisible();
    await waitFor(() => expect(section().queryByRole("alert")).not.toBeInTheDocument());
    expect(saveState()).toMatch(SETTLED_SAVED);
    expect(posts).toEqual(["Accepted once"]);
    expect(reads.length).toBeGreaterThan(before);
  });
});

describe("what the footer says across write and read phases", () => {
  it("keeps an unsaved write's label when a read-only recovery succeeds", async () => {
    const { result } = renderHook(() => useDetailSession(), { wrapper: DetailSessionProvider });
    await act(async () => { await result.current.track("task-id", Promise.reject(new Error("Refused"))).catch(() => {}); });
    expect(result.current.saveStatus("task-id")).toBe("failed");
    await act(async () => { await result.current.track("task-id", Promise.resolve(canonical()), "refresh"); });
    expect(result.current.saveStatus("task-id")).toBe("failed");
    // A write that lands still settles the task, as it always did.
    await act(async () => { await result.current.track("task-id", Promise.resolve(canonical())); });
    expect(result.current.saveStatus("task-id")).toBe("idle");
  });

  it("still clears a failed readback once the read succeeds", async () => {
    const saved = { taskId: "task-id", kind: "comment", childId: "c0" } as const;
    const { result } = renderHook(() => useDetailSession(), { wrapper: DetailSessionProvider });
    await act(async () => { await result.current.track("task-id", Promise.reject(new TaskReadbackError(saved))).catch(() => {}); });
    expect(result.current.saveStatus("task-id")).toBe("refresh");
    await act(async () => { await result.current.track("task-id", Promise.resolve(canonical()), "refresh"); });
    expect(result.current.saveStatus("task-id")).toBe("idle");
  });
});
