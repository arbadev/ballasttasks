import { statusName } from "../model/statuses";
import type { ActivityEntry, Attachment, Task, TaskStatus } from "../model/types";
import type { InMemoryTaskStore } from "./inMemoryTaskStore";
import type { NewTask, TaskPatch, TaskService } from "./types";

/** Explicit demo adapter. Mutation event wording follows domain/activity_log.py in the API. */
export class InMemoryTaskService implements TaskService {
  constructor(private readonly store: InMemoryTaskStore) {}

  async list(): Promise<Task[]> {
    return this.store.all();
  }

  async get(id: string): Promise<Task | null> {
    return this.store.find(id);
  }

  async create(input: NewTask): Promise<Task> {
    const now = this.store.now();
    const task: Task = {
      id: this.store.nextId("t"),
      title: input.title,
      description: "",
      status: input.status ?? "todo",
      project: input.project ?? "inbox",
      assignee: null,
      due: null,
      prio: 2,
      importance: 50,
      steps: [],
      attachments: [],
      activity: [this.log("Created the task", now)],
      createdAt: now,
      updatedAt: now,
    };
    this.store.prepend(task);
    return task;
  }

  async update(id: string, patch: TaskPatch, note?: string): Promise<Task> {
    void note; // Deprecated compatibility hint, not an event-writing capability.
    const clean = { ...patch };
    if (clean.importance !== undefined) clean.importance = Math.max(0, Math.min(100, clean.importance));
    return this.store.replace(id, (task) => {
      const logs: string[] = [];
      const assignment = this.assignmentNote(task, clean);
      if (assignment) logs.push(assignment);
      if (clean.due !== undefined && clean.due !== task.due) logs.push(this.dueNote(task.due, clean.due));
      if (clean.prio !== undefined && clean.prio !== task.prio) logs.push(`Priority P${task.prio} → P${clean.prio}`);
      return this.touch({ ...task, ...clean }, logs);
    });
  }

  async move(id: string, status: TaskStatus): Promise<Task> {
    const task = this.store.require(id);
    if (task.status === status) return task;
    return this.store.replace(id, (t) =>
      this.touch({ ...t, status }, `Moved ${statusName(t.status)} → ${statusName(status)}`),
    );
  }

  async toggleDone(id: string): Promise<Task> {
    const task = this.store.require(id);
    return this.move(id, task.status === "done" ? "todo" : "done");
  }

  async addStep(id: string, text: string): Promise<Task> {
    const trimmed = text.trim();
    if (!trimmed) return this.store.require(id);
    return this.store.replace(id, (t) => {
      if (t.steps.length >= 100) throw new Error("A task can hold at most 100 steps.");
      return this.touch({ ...t, steps: [...t.steps, { id: this.store.nextId("s"), text: trimmed, done: false }] }, `Added step “${trimmed}”`);
    });
  }

  async toggleStep(id: string, stepId: string): Promise<Task> {
    return this.store.replace(id, (t) =>
      this.touch({ ...t, steps: t.steps.map((s) => (s.id === stepId ? { ...s, done: !s.done } : s)) },
        t.steps.find((s) => s.id === stepId && !s.done) ? `Completed step “${t.steps.find((s) => s.id === stepId)!.text}”` : undefined),
    );
  }

  async removeStep(id: string, stepId: string): Promise<Task> {
    return this.store.replace(id, (t) => this.touch({ ...t, steps: t.steps.filter((s) => s.id !== stepId) }));
  }

  async addComment(id: string, text: string): Promise<Task> {
    const trimmed = text.trim();
    if (!trimmed) return this.store.require(id);
    const now = this.store.now();
    const entry: ActivityEntry = { type: "comment", who: this.store.currentUserId, text: trimmed, at: now };
    return this.store.replace(id, (t) => ({ ...t, activity: [...t.activity, entry], updatedAt: now }));
  }

  async addAttachment(id: string, attachment: Attachment, file?: File): Promise<Task> {
    // Deliberately do not read or retain bytes in this metadata-only adapter.
    void file;
    return this.store.replace(id, (t) =>
      this.touch({ ...t, attachments: [...t.attachments, attachment] }, `Attached ${attachment.name}`),
    );
  }

  async remove(id: string): Promise<void> {
    this.store.delete(id);
  }

  private assignmentNote(task: Task, patch: TaskPatch): string | undefined {
    if (patch.assignee === undefined || patch.assignee === task.assignee) return undefined;
    return patch.assignee ? `Assigned to ${this.store.personName(patch.assignee)}` : "Unassigned";
  }

  private dueNote(old: string | null, next: string | null): string {
    if (next === null) return "Due date cleared";
    const today = new Date(this.store.now()).toISOString().slice(0, 10);
    const after = (date: string, days: number) => new Date(Date.parse(`${date}T00:00:00Z`) + days * 86_400_000).toISOString().slice(0, 10);
    if (next === after(today, 1)) return "Due date moved to tomorrow";
    if (next === after(old && old > today ? old : today, 7)) return "Due date moved a week out";
    const date = new Date(`${next}T00:00:00Z`);
    const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][date.getUTCMonth()];
    return `Due date moved to ${month} ${date.getUTCDate()}${next.slice(0, 4) === today.slice(0, 4) ? "" : `, ${date.getUTCFullYear()}`}`;
  }

  private log(text: string, at: number): ActivityEntry {
    return { type: "log", who: this.store.currentUserId, text, at };
  }

  /** Stamps updatedAt and, when there is something to say, appends a log entry. */
  private touch(task: Task, logText?: string | string[]): Task {
    const now = this.store.now();
    const logs = typeof logText === "string" ? [logText] : logText ?? [];
    return { ...task, updatedAt: now, activity: logs.length ? [...task.activity, ...logs.map((text) => this.log(text, now))] : task.activity };
  }
}
