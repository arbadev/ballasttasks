import type { Task } from "../model/types";
import type { InMemoryTaskStore } from "./inMemoryTaskStore";
import { draftStepsFor } from "./stepDrafts";
import type { Generation, StepGenerationService } from "./types";

/** How long the explicit demo provider takes to propose, as in the design. */
export const GENERATION_DELAY_MS = 2200;

/** Demo proposals share the HTTP contract: per-task, local discard, atomic acceptance. */
export class InMemoryStepGenerationService implements StepGenerationService {
  private readonly generations = new Map<string, Generation>();
  private readonly timers = new Map<string, ReturnType<typeof setTimeout>>();
  private selected: string | null = null;
  private readonly listeners = new Set<(generation: Generation | null) => void>();

  constructor(private readonly store: InMemoryTaskStore) {}

  async start(taskId: string): Promise<void> {
    const task = this.store.require(taskId);
    this.selected = taskId;
    if (this.generations.get(taskId)?.phase === "running") return;
    this.generations.set(taskId, { taskId, phase: "running" });
    this.emit();
    this.timers.set(taskId, setTimeout(() => {
      this.timers.delete(taskId);
      if (!this.store.find(taskId)) return this.forget(taskId);
      const steps = draftStepsFor(task.id).map((text) => ({ id: this.store.nextId("s"), text }));
      this.generations.set(taskId, { taskId, phase: "proposed", steps });
      this.emit();
    }, GENERATION_DELAY_MS));
  }

  current(): Generation | null {
    return this.selected ? this.generations.get(this.selected) ?? null : null;
  }

  select(taskId: string | null): void { this.selected = taskId; this.emit(); }

  subscribe(listener: (generation: Generation | null) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  removeProposed(stepId: string): void {
    const g = this.current();
    if (g?.phase !== "proposed") return;
    this.generations.set(g.taskId, { ...g, steps: g.steps.filter((s) => s.id !== stepId) });
    this.emit();
  }

  async accept(): Promise<Task | null> {
    const g = this.current();
    if (g?.phase !== "proposed" || !g.steps.length) return null;
    if (!this.store.find(g.taskId)) {
      this.forget(g.taskId);
      return null;
    }
    const n = g.steps.length;
    const now = this.store.now();
    const task = this.store.replace(g.taskId, (t) => {
      if (t.steps.length + n > 100) throw new Error("A task can hold at most 100 steps. No steps were added.");
      return {
        ...t, updatedAt: now,
        steps: [...t.steps, ...g.steps.map((s) => ({ id: s.id, text: s.text, done: false }))],
        activity: [...t.activity, { type: "log", who: this.store.currentUserId, text: `Drafted ${n} step${n === 1 ? "" : "s"} · added by ${this.actor()}`, at: now }],
      };
    });
    this.forget(g.taskId);
    return task;
  }

  async discard(): Promise<void> { if (this.selected && this.generations.has(this.selected)) this.forget(this.selected); }

  forget(taskId: string): void {
    clearTimeout(this.timers.get(taskId));
    this.timers.delete(taskId);
    this.generations.delete(taskId);
    this.emit();
  }

  dispose(): void {
    for (const timer of this.timers.values()) clearTimeout(timer);
    this.timers.clear();
    this.generations.clear();
    this.selected = null;
    this.listeners.clear();
  }

  private actor(): string { return this.store.personName(this.store.currentUserId).split(" ")[0]; }
  private emit(): void { this.listeners.forEach((listener) => listener(this.current())); }
}
