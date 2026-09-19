import { statusName } from "../model/statuses";
import type { ActivityEntry, Attachment, Task, TaskStatus } from "../model/types";
import type { InMemoryTaskStore } from "./inMemoryTaskStore";
import type { NewTask, TaskPatch, TaskService } from "./types";

/** TaskService over the shared in-memory store. Logs activity exactly as the design does. */
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
    const clean = { ...patch };
    if (clean.importance !== undefined) clean.importance = Math.max(0, Math.min(100, clean.importance));
    return this.store.replace(id, (task) => {
      const text = note ?? this.assignmentNote(task, clean);
      return this.touch({ ...task, ...clean }, text);
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
    return this.store.replace(id, (t) =>
      this.touch({ ...t, steps: [...t.steps, { id: this.store.nextId("s"), text: trimmed, done: false }] }),
    );
  }

  async toggleStep(id: string, stepId: string): Promise<Task> {
    return this.store.replace(id, (t) =>
      this.touch({ ...t, steps: t.steps.map((s) => (s.id === stepId ? { ...s, done: !s.done } : s)) }),
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

  private log(text: string, at: number): ActivityEntry {
    return { type: "log", who: this.store.currentUserId, text, at };
  }

  /** Stamps updatedAt and, when there is something to say, appends a log entry. */
  private touch(task: Task, logText?: string): Task {
    const now = this.store.now();
    return { ...task, updatedAt: now, activity: logText ? [...task.activity, this.log(logText, now)] : task.activity };
  }
}
