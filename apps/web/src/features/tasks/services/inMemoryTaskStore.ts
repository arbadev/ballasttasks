import type { Task } from "../model/types";
import { CURRENT_USER_ID, SEED_PEOPLE, seedTasks } from "./seed";
import { TaskNotFoundError, type Clock } from "./types";

/**
 * The state shared by the in-memory services: the tasks, the clock and one id sequence for
 * tasks and steps. Tasks are replaced, never mutated, so a task handed out stays as it was.
 */
export class InMemoryTaskStore {
  private tasks: Task[];
  private sequence: number;
  readonly currentUserId = CURRENT_USER_ID;

  constructor(readonly now: Clock) {
    const seeded = seedTasks(now());
    this.tasks = seeded;
    // Continue after the highest seeded step id, as the design's single counter does.
    this.sequence = Math.max(100, ...seeded.flatMap((t) => t.steps.map((s) => Number(s.id.slice(1)))));
  }

  nextId(prefix: "t" | "s"): string {
    return `${prefix}${++this.sequence}`;
  }

  all(): Task[] {
    return [...this.tasks];
  }

  find(id: string): Task | null {
    return this.tasks.find((t) => t.id === id) ?? null;
  }

  require(id: string): Task {
    const task = this.find(id);
    if (!task) throw new TaskNotFoundError(id);
    return task;
  }

  prepend(task: Task): void {
    this.tasks = [task, ...this.tasks];
  }

  /** Replaces the task with `change(task)` and returns the new value. */
  replace(id: string, change: (task: Task) => Task): Task {
    const next = change(this.require(id));
    this.tasks = this.tasks.map((t) => (t.id === id ? next : t));
    return next;
  }

  delete(id: string): void {
    this.require(id);
    this.tasks = this.tasks.filter((t) => t.id !== id);
  }

  personName(id: string): string {
    return SEED_PEOPLE.find((p) => p.id === id)?.name ?? "Unknown";
  }
}
