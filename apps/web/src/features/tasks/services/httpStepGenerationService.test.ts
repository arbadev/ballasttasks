import { afterEach, describe, expect, it, vi } from "vitest";
import type { HttpTransport } from "@/lib/api/client";
import { ApiError } from "@/lib/api/client";
import { makeTask } from "@/test/tasks";
import { HttpStepGenerationService } from "./httpStepGenerationService";

function setup() {
  vi.useFakeTimers();
  let state = "pending";
  const request = vi.fn().mockImplementation(async (_path, options) => ({ id: "job", task_id: options?.body?.task_id ?? "a", state: "pending", titles: [], error: null }));
  const get = vi.fn().mockImplementation(async () => ({ id: "job", task_id: "a", state, titles: state === "success" ? ["one", "two"] : [], error: state === "failure" ? "timeout" : null }));
  const client = { get, request, download: vi.fn() } as HttpTransport;
  const acceptSteps = vi.fn().mockResolvedValue(makeTask({ id: "a" }));
  const service = new HttpStepGenerationService(client, { acceptSteps }, () => Date.now());
  const unsubscribe = service.subscribe(() => {});
  return { service, get, request, acceptSteps, unsubscribe, state: (value: string) => { state = value; } };
}
afterEach(() => vi.useRealTimers());

describe("retained HTTP generation handles", () => {
  it("polls at 2/4/8/10 seconds, stops at success, and writes only on atomic acceptance", async () => {
    const { service, get, acceptSteps, state } = setup();
    await service.start("a");
    for (const delay of [2000, 4000, 8000, 10000]) {
      const before = get.mock.calls.length;
      await vi.advanceTimersByTimeAsync(delay - 1);
      expect(get).toHaveBeenCalledTimes(before);
      await vi.advanceTimersByTimeAsync(1);
      expect(get).toHaveBeenCalledTimes(before + 1);
    }
    state("success");
    await vi.advanceTimersByTimeAsync(10000);
    expect(service.current()?.phase).toBe("proposed");
    expect(acceptSteps).not.toHaveBeenCalled();
    const polls = get.mock.calls.length;
    await vi.advanceTimersByTimeAsync(60000);
    expect(get).toHaveBeenCalledTimes(polls);
    const proposal = service.current();
    if (proposal?.phase !== "proposed") throw new Error("expected proposal");
    service.removeProposed(proposal.steps[1].id);
    await Promise.all([service.accept(), service.accept()]);
    expect(acceptSteps).toHaveBeenCalledExactlyOnceWith("a", ["one"]);
    expect(service.current()).toBeNull();
  });

  it("pauses while unselected, hidden or unobserved and resumes the same task handle", async () => {
    const { service, get, request, unsubscribe } = setup();
    await service.start("a");
    service.select("b");
    await vi.advanceTimersByTimeAsync(20000);
    expect(service.current()).toBeNull();
    expect(get).not.toHaveBeenCalled();
    service.select("a");
    await vi.advanceTimersByTimeAsync(2000);
    expect(get).toHaveBeenLastCalledWith("/tasks/a/step-generations/job");
    service.setVisible(false);
    await vi.advanceTimersByTimeAsync(20000);
    expect(get).toHaveBeenCalledTimes(1);
    service.setVisible(true);
    unsubscribe();
    await vi.advanceTimersByTimeAsync(20000);
    expect(get).toHaveBeenCalledTimes(1);
    service.subscribe(() => {});
    await vi.advanceTimersByTimeAsync(4000);
    expect(get).toHaveBeenCalledTimes(2);
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("honors 429 Retry-After even after navigating away and back", async () => {
    const { service, get } = setup();
    get.mockRejectedValueOnce(new ApiError("limited", { kind: "http", status: 429, retryAfterSeconds: 30 }));
    await service.start("a");
    await vi.advanceTimersByTimeAsync(2000);
    expect(service.current()?.phase).toBe("running");
    service.select("b");
    service.select("a");
    await vi.advanceTimersByTimeAsync(29999);
    expect(get).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("stops on expired/unknown/deleted-task 404 and never accepts stale results after deletion", async () => {
    const { service, get, acceptSteps } = setup();
    get.mockRejectedValueOnce(new ApiError("missing", { kind: "http", status: 404 }));
    await service.start("a");
    await vi.advanceTimersByTimeAsync(2000);
    expect(service.current()).toMatchObject({ phase: "error", message: expect.stringMatching(/expired|deleted/) });
    await vi.advanceTimersByTimeAsync(30000);
    expect(get).toHaveBeenCalledTimes(1);
    service.forget("a");
    expect(await service.accept()).toBeNull();
    expect(acceptSteps).not.toHaveBeenCalled();
  });

  it("ignores an obsolete in-flight response after disposal", async () => {
    const { service, get } = setup();
    let resolve!: (value: unknown) => void;
    get.mockImplementation(() => new Promise((done) => { resolve = done; }));
    await service.start("a");
    await vi.advanceTimersByTimeAsync(2000);
    service.dispose();
    resolve({ state: "success", titles: ["late"], id: "job", task_id: "a", error: null });
    await vi.advanceTimersByTimeAsync(10000);
    expect(service.current()).toBeNull();
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("retains proposals after a rejected 100-step ceiling and never adds partially", async () => {
    const { service, acceptSteps, state } = setup();
    await service.start("a");
    state("success");
    await vi.advanceTimersByTimeAsync(2000);
    acceptSteps.mockRejectedValueOnce(new ApiError("limit", { kind: "http", status: 422 }));
    await expect(service.accept()).rejects.toMatchObject({ status: 422 });
    expect(service.current()).toMatchObject({ phase: "proposed", accepting: false });
    expect(acceptSteps).toHaveBeenCalledTimes(1);
  });
});
