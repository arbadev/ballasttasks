import { ApiError, type HttpTransport } from "@/lib/api/client";
import type { Attachment, Task, TaskStatus } from "../model/types";
import { TaskNotFoundError, type NewTask, type TaskPatch, type TaskService } from "./types";
import { apiStatus, attachmentFromApi, taskFromApi, type Schemas } from "./httpMapping";

const pathFor = (id: string) => `/tasks/${encodeURIComponent(id)}`;

/** Complete list, selected detail only; workspace remains the sole owner of loaded data. */
export class HttpTaskService implements TaskService {
  private writes = new Map<string, Promise<unknown>>();
  constructor(private readonly client: HttpTransport) {}

  async list(): Promise<Task[]> {
    const tasks = new Map<string, Task>();
    let offset = 0;
    for (;;) {
      const page = await this.client.get<Schemas["TaskListResponse"]>(`/tasks?status=all&limit=200&offset=${offset}`);
      for (const row of page.items) tasks.set(row.id, taskFromApi(row));
      offset += page.items.length;
      if (offset >= page.total) return [...tasks.values()];
      if (!page.items.length) throw new Error("The task list changed while loading. Please retry.");
    }
  }

  async get(id: string): Promise<Task | null> {
    try {
      const row = await this.client.get<Schemas["TaskDetailResponse"]>(pathFor(id));
      const activity: Schemas["ActivityEntryResponse"][] = [];
      let offset = 0;
      for (;;) {
        const page = await this.client.get<Schemas["ActivityListResponse"]>(`${pathFor(id)}/activity?limit=200&offset=${offset}`);
        activity.push(...page.items);
        offset += page.items.length;
        if (offset >= page.total) break;
        if (!page.items.length) throw new Error("The activity changed while loading. Please retry.");
      }
      return {
        ...taskFromApi(row), detailLoaded: true,
        steps: row.steps.map((step) => ({ id: step.id, text: step.title, done: step.done })),
        attachments: row.attachments.map(attachmentFromApi),
        activity: activity.reverse().map((entry) => ({ type: entry.kind, who: entry.actor.id, text: entry.text, at: Date.parse(entry.created_at) })),
      };
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  }

  async create(input: NewTask): Promise<Task> {
    const row = await this.client.request<Schemas["TaskResponse"]>("/tasks", {
      method: "POST", body: {
        title: input.title, ...(input.status ? { status: apiStatus(input.status) } : {}),
        ...(input.project && input.project !== "inbox" ? { project_id: input.project } : {}),
      } satisfies Pick<Schemas["TaskCreate"], "title"> & Partial<Schemas["TaskCreate"]>,
    });
    return this.require(row.id);
  }

  /** Legacy note is deliberately ignored: only the API writes activity events. */
  update(id: string, patch: TaskPatch, _note?: string): Promise<Task> {
    void _note;
    const body: Schemas["TaskUpdate"] = {};
    if (patch.title !== undefined) body.title = patch.title;
    if (patch.description !== undefined) body.description = patch.description;
    if (patch.assignee !== undefined) body.assignee_id = patch.assignee;
    if (patch.due !== undefined) body.due_date = patch.due;
    if (patch.prio !== undefined) body.priority = (["P0", "P1", "P2", "P3"] as const)[patch.prio];
    if (patch.importance !== undefined) body.importance = patch.importance;
    if (patch.project !== undefined) body.project_id = patch.project;
    return this.change(id, () => this.client.request(pathFor(id), { method: "PATCH", body }));
  }

  move(id: string, status: TaskStatus): Promise<Task> {
    return this.change(id, () => this.client.request(pathFor(id), { method: "PATCH", body: { status: apiStatus(status) } }));
  }

  toggleDone(id: string): Promise<Task> {
    return this.change(id, async () => {
      const task = await this.client.get<Schemas["TaskResponse"]>(pathFor(id));
      await this.client.request(pathFor(id), { method: "PATCH", body: { status: task.status === "done" ? "todo" : "done" } });
    });
  }

  addStep(id: string, text: string): Promise<Task> {
    return this.change(id, () => text.trim() ? this.client.request(`${pathFor(id)}/steps`, { method: "POST", body: { title: text.trim() } }) : Promise.resolve());
  }

  toggleStep(id: string, stepId: string): Promise<Task> {
    return this.change(id, async () => {
      const task = await this.client.get<Schemas["TaskDetailResponse"]>(pathFor(id));
      const step = task.steps.find((step) => step.id === stepId);
      if (!step) throw new Error("This step no longer exists. Reload the task.");
      await this.client.request(`${pathFor(id)}/steps/${encodeURIComponent(stepId)}`, { method: "PATCH", body: { done: !step.done } });
    });
  }

  removeStep(id: string, stepId: string): Promise<Task> {
    return this.change(id, () => this.client.request(`${pathFor(id)}/steps/${encodeURIComponent(stepId)}`, { method: "DELETE" }));
  }

  acceptSteps(id: string, titles: string[]): Promise<Task> {
    return this.change(id, () => this.client.request(`${pathFor(id)}/steps/bulk`, { method: "POST", body: { titles } }));
  }

  addComment(id: string, text: string): Promise<Task> {
    return this.change(id, () => text.trim() ? this.client.request(`${pathFor(id)}/comments`, { method: "POST", body: { text: text.trim() } }) : Promise.resolve());
  }

  addAttachment(id: string, attachment: Attachment): Promise<Task> {
    if (attachment.kind !== "link" || !attachment.url) return Promise.reject(new Error("Choose a file to upload, or enter an absolute link URL."));
    return this.change(id, () => this.client.request(`${pathFor(id)}/attachments/links`, {
      method: "POST", body: { name: attachment.name, url: attachment.url },
    }));
  }

  uploadAttachment(id: string, file: File): Promise<Task> {
    const body = new FormData();
    body.append("file", file);
    return this.change(id, () => this.client.request(`${pathFor(id)}/attachments/files`, { method: "POST", body }));
  }

  downloadAttachment(id: string, attachmentId: string): Promise<Blob> {
    return this.client.download(`${pathFor(id)}/attachments/${encodeURIComponent(attachmentId)}/content`);
  }

  removeAttachment(id: string, attachmentId: string): Promise<Task> {
    return this.change(id, () => this.client.request(`${pathFor(id)}/attachments/${encodeURIComponent(attachmentId)}`, { method: "DELETE" }));
  }

  remove(id: string): Promise<void> {
    return this.serial(id, () => this.client.request<void>(pathFor(id), { method: "DELETE" }));
  }

  private async require(id: string): Promise<Task> {
    const task = await this.get(id);
    if (!task) throw new TaskNotFoundError(id);
    return task;
  }

  private change(id: string, write: () => Promise<unknown>): Promise<Task> {
    return this.serial(id, async () => { await write(); return this.require(id); });
  }

  /** Serializes read/modify/write gestures and canonical reloads for one task, not other tasks. */
  private serial<T>(id: string, action: () => Promise<T>): Promise<T> {
    const result = (this.writes.get(id) ?? Promise.resolve()).catch(() => {}).then(action).catch((error: unknown) => {
      if (error instanceof ApiError && error.status === 404) throw new TaskNotFoundError(id);
      throw error;
    });
    this.writes.set(id, result);
    const clean = () => { if (this.writes.get(id) === result) this.writes.delete(id); };
    void result.then(clean, clean);
    return result;
  }
}
