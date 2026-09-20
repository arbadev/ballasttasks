import { ApiError, type HttpTransport } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { Task } from "../model/types";
import type { Clock, Generation, StepGenerationService } from "./types";

type Job = components["schemas"]["StepGenerationResponse"];
interface Handle {
  taskId: string;
  jobId?: string;
  value: Generation;
  attempt: number;
  dueAt: number;
  polling?: boolean;
  accepting?: Promise<Task | null>;
}
const delays = [2000, 4000, 8000, 10000];

/** No server cancellation, quota or latest-job lookup. Handles live only in this login's memory. */
export class HttpStepGenerationService implements StepGenerationService {
  private handles = new Map<string, Handle>();
  private selected: string | null = null;
  private visible = true;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private listeners = new Set<(value: Generation | null) => void>();

  constructor(
    private readonly client: HttpTransport,
    private readonly tasks: { acceptSteps(id: string, titles: string[]): Promise<Task> },
    private readonly clock: Clock,
  ) {}

  current = (): Generation | null => this.selected ? this.handles.get(this.selected)?.value ?? null : null;
  subscribe = (listener: (value: Generation | null) => void): (() => void) => {
    this.listeners.add(listener);
    this.schedule();
    return () => { this.listeners.delete(listener); this.schedule(); };
  };

  select(taskId: string | null): void { this.selected = taskId; this.emit(); }
  setVisible(visible: boolean): void { this.visible = visible; this.schedule(); }

  async start(taskId: string): Promise<void> {
    const handle: Handle = { taskId, value: { taskId, phase: "running" }, attempt: 0, dueAt: 0 };
    this.handles.set(taskId, handle);
    this.selected = taskId;
    this.emit();
    try {
      const job = await this.client.request<Job>(`/tasks/${encodeURIComponent(taskId)}/step-generations`, { method: "POST" });
      if (!this.owns(handle)) return;
      handle.jobId = job.id;
      handle.dueAt = this.clock() + delays[0];
      this.apply(handle, job);
    } catch (error) {
      if (this.owns(handle)) {
        handle.value = { taskId, phase: "error", message: error instanceof ApiError && error.status === 429
          ? `Too many requests. Try again in ${error.retryAfterSeconds ?? 60} seconds.`
          : "Could not start generation. Please try again." };
        this.emit();
      }
      throw error;
    }
  }

  removeProposed(stepId: string): void {
    const handle = this.active();
    if (!handle || handle.value.phase !== "proposed" || handle.accepting) return;
    handle.value = { ...handle.value, steps: handle.value.steps.filter((step) => step.id !== stepId) };
    this.emit();
  }

  accept(): Promise<Task | null> {
    const handle = this.active();
    if (!handle) return Promise.resolve(null);
    if (handle.accepting) return handle.accepting;
    if (handle.value.phase !== "proposed" || !handle.value.steps.length) return Promise.resolve(null);
    const proposal = handle.value;
    handle.value = { ...proposal, accepting: true };
    const pending = this.tasks.acceptSteps(handle.taskId, proposal.steps.map((step) => step.text))
      .then((task) => {
        if (!this.owns(handle)) return null;
        this.handles.delete(handle.taskId);
        this.emit();
        return task;
      }).catch((error: unknown) => {
        if (this.owns(handle)) {
          // A 422 rejected the whole batch. Other failures may have lost an acknowledgement:
          // do not offer a blind retry that could duplicate accepted steps.
          handle.value = error instanceof ApiError && error.status === 422
            ? { ...proposal, accepting: false, notice: "No steps were added. Check the 100-step limit and selected proposals." }
            : { taskId: handle.taskId, phase: "error", recovery: "reload", message: "Acceptance could not be confirmed. Reload the task before generating again." };
          this.emit();
        }
        throw error;
      }).finally(() => { handle.accepting = undefined; });
    handle.accepting = pending;
    this.emit();
    return pending;
  }

  async discard(): Promise<void> { if (this.selected) this.forget(this.selected); }
  forget(taskId: string): void { this.handles.delete(taskId); this.emit(); }
  dispose(): void { this.handles.clear(); this.selected = null; this.stop(); this.listeners.clear(); }

  private active(): Handle | undefined { return this.selected ? this.handles.get(this.selected) : undefined; }
  private owns(handle: Handle): boolean { return this.handles.get(handle.taskId) === handle; }
  private stop(): void { clearTimeout(this.timer); this.timer = undefined; }
  private emit(): void { for (const listener of this.listeners) listener(this.current()); this.schedule(); }

  private schedule(): void {
    this.stop();
    const handle = this.active();
    if (!this.visible || !this.listeners.size || !handle?.jobId || handle.polling || handle.value.phase !== "running") return;
    this.timer = setTimeout(() => { void this.poll(handle); }, Math.max(0, handle.dueAt - this.clock()));
  }

  private async poll(handle: Handle): Promise<void> {
    handle.polling = true;
    try {
      const job = await this.client.get<Job>(`/tasks/${encodeURIComponent(handle.taskId)}/step-generations/${encodeURIComponent(handle.jobId!)}`);
      if (!this.owns(handle)) return;
      handle.attempt += 1;
      handle.dueAt = this.clock() + delays[Math.min(handle.attempt, delays.length - 1)];
      this.apply(handle, job);
    } catch (error) {
      if (!this.owns(handle)) return;
      if (error instanceof ApiError && (error.status === 404 || error.status === 401 || error.kind === "session")) {
        handle.value = { taskId: handle.taskId, phase: "error", recovery: "reload", message: error.status === 404
          ? "This generation expired or its task was deleted. Reload the task."
          : "This session ended. Sign in again." };
      } else {
        const seconds = error instanceof ApiError && error.status === 429 ? error.retryAfterSeconds ?? 10 : 10;
        handle.dueAt = this.clock() + Math.max(1, seconds) * 1000;
        handle.value = { taskId: handle.taskId, phase: "running", notice: "Waiting to retry the status check…" };
      }
      this.emit();
    } finally {
      handle.polling = false;
      this.schedule();
    }
  }

  private apply(handle: Handle, job: Job): void {
    if (job.state === "success") {
      handle.value = { taskId: handle.taskId, phase: "proposed", steps: job.titles.map((text, i) => ({ id: `${job.id}:${i}`, text })) };
    } else if (job.state === "failure") {
      handle.value = { taskId: handle.taskId, phase: "error", message: job.error === "timeout" ? "Generation timed out. Try again." : "Generation failed. Try again." };
    }
    this.emit();
  }
}
