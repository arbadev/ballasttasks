import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { Providers } from "@/app/providers";
import { ApiClient } from "@/lib/api/client";
import { apiPerson, apiTask } from "@/test/httpFixtures";
import { FakeDirectoryService, FakeStepGenerationService, FakeTaskService } from "@/test/fakeServices";
import { server } from "@/test/server";
import { makeTask, NOW } from "@/test/tasks";
import { HttpTaskService } from "../services/httpTaskService";
import { TaskReadbackError } from "../services/types";
import { WorkspaceProvider, useWorkspace } from "../workspace/WorkspaceProvider";
import { composerKey, DetailSessionProvider, useComposer, useDetailSession } from "./DetailSession";
import { TaskDetail } from "./TaskDetail";

const base = "http://write-readback.test";
type Kind = "comment" | "step";
type Read = "detail" | "activity";

function setup(kind: Kind, failingRead: Read = "detail", rejectPost = false, client = new ApiClient(base)) {
  const stored: string[] = [];
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
      stored.push(text);
      return HttpResponse.json({ id: `saved-${stored.length}` }, { status: 201 });
    }),
    http.get(`${base}/tasks/task-id`, () => {
      reads.push("detail");
      if (deleted) return HttpResponse.json({ detail: "Not found" }, { status: 404 });
      if (failRead("detail")) return HttpResponse.json({ detail: "Read unavailable" }, { status: 503 });
      return HttpResponse.json(apiTask({
        steps: kind === "step" ? stored.map((title, position) => ({ id: `s${position}`, task_id: "task-id", title, done: false, position, created_at: "2026-09-19T00:00:00Z" })) : [],
        steps_total: kind === "step" ? stored.length : 0,
        comments_count: kind === "comment" ? stored.length : 0,
      }));
    }),
    http.patch(`${base}/tasks/task-id`, () => HttpResponse.json(apiTask())),
    http.get(`${base}/tasks/task-id/activity`, () => {
      reads.push("activity");
      if (failRead("activity")) return HttpResponse.json({ detail: "Activity unavailable" }, { status: 503 });
      const items = kind === "comment" ? stored.map((text, i) => ({ id: `c${i}`, task_id: "task-id", kind: "comment", actor: apiPerson, text, created_at: "2026-09-19T00:00:00Z" })) : [];
      return HttpResponse.json({ items, total: items.length, limit: 200, offset: 0 });
    }),
  );
  const service = new HttpTaskService(client);
  const send = (text: string) => kind === "comment" ? service.addComment("task-id", text) : service.addStep("task-id", text);
  return { service, send, stored, posts, reads, failAgain: () => { readFailures = 1; }, deleteTask: () => { deleted = true; } };
}

// Carried from the scout: actual HTTP adapter/client and composer, not a mocked send.
describe("acknowledged composer write with failed readback", () => {
  it.each(["comment", "step"] as const)("recovers the acknowledged %s without a second POST", async (kind) => {
    const { service, send, stored, posts } = setup(kind);
    const { result } = renderHook(() => useComposer(`${kind}:task-id`, send, () => service.get("task-id")), { wrapper: DetailSessionProvider });
    act(() => result.current.setText("Accepted once"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.failed).toBe("Accepted once"));
    expect(stored).toEqual(["Accepted once"]);
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(posts).toEqual(["Accepted once"]);
    expect(stored).toEqual(["Accepted once"]);
    expect(result.current.text).toBe("");
  });

  it("retains genuine POST refusal recovery", async () => {
    const { service, send, stored, posts } = setup("comment", "detail", true);
    const { result } = renderHook(() => useComposer("comment:task-id", send, () => service.get("task-id")), { wrapper: DetailSessionProvider });
    act(() => result.current.setText("Refused once"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.failed).toBe("Refused once"));
    expect(stored).toEqual([]);
    expect(result.current.text).toBe("Refused once");
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(posts).toEqual(["Refused once", "Refused once"]);
    expect(stored).toEqual(["Refused once"]);
    expect(result.current.text).toBe("");
  });
});

describe("readback recovery boundaries", () => {
  it("does not restore already-saved text after a genuine refusal was retried", async () => {
    const { service, send, stored, posts, failAgain } = setup("comment", "detail", true);
    const { result } = renderHook(() => useComposer("comment:task-id", send, () => service.refresh("task-id")), { wrapper: DetailSessionProvider });
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
    expect(stored).toEqual(["Refused then saved"]);
    expect(posts).toHaveLength(2);
  });

  it("retains an independently retyped identical draft after read recovery", async () => {
    const { service, send, posts } = setup("step");
    const { result } = renderHook(() => useComposer("step:task-id", send, () => service.refresh("task-id")), { wrapper: DetailSessionProvider });
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
    const { send, service, stored } = setup("comment", "detail", true);
    await expect(send("Refused")).rejects.toMatchObject({ status: 422 });
    expect(stored).toEqual([]);
    server.use(http.get(`${base}/tasks/task-id`, () => HttpResponse.json({}, { status: 503 })));
    await expect(service.addComment("task-id", " ")).rejects.toMatchObject({ status: 503 });
  });
});

function Openers() {
  const { actions } = useWorkspace();
  return <button onClick={() => actions.selectTask("task-id")}>Open task</button>;
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
    const { posts, stored, section, box, failAgain } = await renderPanel(kind, read);
    expect(await section().findByRole("alert")).toHaveTextContent(/was saved/i);
    expect(section().queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(screen.getByTestId("save-state")).not.toHaveTextContent("not saved");
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
    expect(stored).toEqual(["Accepted once"]);
    expect(posts).toEqual(["Accepted once"]);
    expect(screen.getByTestId("save-state")).toHaveTextContent("saved");
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
    const { posts, stored, section, box } = await renderPanel(kind, "detail");
    expect(await section().findByRole("alert")).toHaveTextContent(/was saved/i);
    fireEvent.change(screen.getByLabelText("Priority"), { target: { value: "0" } });
    expect(await section().findByText("Accepted once")).toBeVisible();
    await waitFor(() => expect(section().queryByRole("alert")).not.toBeInTheDocument());
    expect(box()).toHaveValue("Independent next draft");
    expect(posts).toEqual(["Accepted once"]);
    expect(stored).toEqual(["Accepted once"]);
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

  it("does not let a reload already outstanding when the write was acknowledged settle it", async () => {
    const { send, service } = setup("comment");
    let land!: (task: unknown) => void;
    const outstanding = new Promise<unknown>((resolve) => { land = resolve; });
    const { result } = renderHook(
      () => ({ session: useDetailSession(), box: useComposer(composerKey("comment", "task-id"), send, () => service.refresh("task-id")) }),
      { wrapper: DetailSessionProvider },
    );
    // A save whose own readback was already in flight cannot have read what is posted next.
    act(() => { void result.current.session.track("task-id", outstanding).catch(() => {}); });
    act(() => result.current.box.setText("Accepted once"));
    act(() => result.current.box.submit());
    await waitFor(() => expect(result.current.box.refreshRequired).toBe(true));
    await act(async () => { land(makeTask({ id: "task-id" })); await outstanding; });
    expect(result.current.box.refreshRequired).toBe(true);
    expect(result.current.box.busy).toBe(true);
  });
});

describe("what the footer says across write and read phases", () => {
  it("keeps an unsaved write's label when a read-only recovery succeeds", async () => {
    const { result } = renderHook(() => useDetailSession(), { wrapper: DetailSessionProvider });
    await act(async () => { await result.current.track("task-id", Promise.reject(new Error("Refused"))).catch(() => {}); });
    expect(result.current.saveStatus("task-id")).toBe("failed");
    await act(async () => { await result.current.track("task-id", Promise.resolve(makeTask({ id: "task-id" })), "refresh"); });
    expect(result.current.saveStatus("task-id")).toBe("failed");
    // A write that lands still settles the task, as it always did.
    await act(async () => { await result.current.track("task-id", Promise.resolve(makeTask({ id: "task-id" }))); });
    expect(result.current.saveStatus("task-id")).toBe("idle");
  });

  it("still clears a failed readback once the read succeeds", async () => {
    const { result } = renderHook(() => useDetailSession(), { wrapper: DetailSessionProvider });
    await act(async () => { await result.current.track("task-id", Promise.reject(new TaskReadbackError())).catch(() => {}); });
    expect(result.current.saveStatus("task-id")).toBe("refresh");
    await act(async () => { await result.current.track("task-id", Promise.resolve(makeTask({ id: "task-id" })), "refresh"); });
    expect(result.current.saveStatus("task-id")).toBe("idle");
  });
});
