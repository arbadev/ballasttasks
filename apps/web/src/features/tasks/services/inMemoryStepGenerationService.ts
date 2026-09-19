import type { Task } from "../model/types";
import type { InMemoryTaskStore } from "./inMemoryTaskStore";
import { draftStepsFor } from "./stepDrafts";
import type { Generation, StepGenerationService } from "./types";

/** How long the assistant "thinks" before proposing, as in the design. */
export const GENERATION_DELAY_MS = 2200;

/** The author id of assistant log entries. */
const ASSISTANT_ID = "ai";

export class InMemoryStepGenerationService implements StepGenerationService {
  private generation: Generation | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private readonly listeners = new Set<(generation: Generation | null) => void>();

  constructor(private readonly store: InMemoryTaskStore) {}

  async start(taskId: string): Promise<void> {
    const task = this.store.require(taskId);
    if (this.generation?.taskId === taskId && this.generation.phase === "running") return;
    this.cancelTimer();
    this.set({ taskId, phase: "running" });
    this.timer = setTimeout(() => {
      this.timer = null;
      if (!this.store.find(taskId)) return this.set(null);
      const steps = draftStepsFor(task.id).map((text) => ({ id: this.store.nextId("s"), text }));
      this.set({ taskId, phase: "proposed", steps });
    }, GENERATION_DELAY_MS);
  }

  current(): Generation | null {
    return this.generation;
  }

  subscribe(listener: (generation: Generation | null) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  removeProposed(stepId: string): void {
    const g = this.generation;
    if (g?.phase !== "proposed") return;
    this.set({ ...g, steps: g.steps.filter((s) => s.id !== stepId) });
  }

  async accept(): Promise<Task | null> {
    const g = this.generation;
    if (g?.phase !== "proposed") return null;
    if (!this.store.find(g.taskId)) {
      this.set(null);
      return null;
    }
    const n = g.steps.length;
    const now = this.store.now();
    const task = this.store.replace(g.taskId, (t) => ({
      ...t,
      updatedAt: now,
      steps: [...t.steps, ...g.steps.map((s) => ({ id: s.id, text: s.text, done: false }))],
      activity: [...t.activity, { type: "log", who: ASSISTANT_ID, text: `Drafted ${n} step${n === 1 ? "" : "s"} · added by ${this.actor()}`, at: now }],
    }));
    this.set(null);
    return task;
  }

  async discard(): Promise<void> {
    const g = this.generation;
    if (!g) return;
    this.cancelTimer();
    if (!this.store.find(g.taskId)) return this.set(null);
    const now = this.store.now();
    // The design leaves updatedAt alone here: a discarded draft did not change the task.
    this.store.replace(g.taskId, (t) => ({
      ...t,
      activity: [...t.activity, { type: "log", who: ASSISTANT_ID, text: `Draft discarded by ${this.actor()}`, at: now }],
    }));
    this.set(null);
  }

  /** The current user's first name, as the assistant's log lines address them. */
  private actor(): string {
    return this.store.personName(this.store.currentUserId).split(" ")[0];
  }

  private cancelTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  private set(generation: Generation | null): void {
    this.generation = generation;
    this.listeners.forEach((listener) => listener(generation));
  }
}
