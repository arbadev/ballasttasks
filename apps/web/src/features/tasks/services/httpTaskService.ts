import { ApiError, type HttpTransport } from "@/lib/api/client";
import type { Attachment, Task, TaskStatus } from "../model/types";
import { TaskNotFoundError, type NewTask, type TaskPatch, type TaskService } from "./types";
import { apiStatus, attachmentFromApi, taskFromApi, type Schemas } from "./httpMapping";
import type { TaskPage, TaskPageRequest } from "./query";

const pathFor = (id: string) => `/tasks/${encodeURIComponent(id)}`;

/** Complete list, selected detail only; workspace remains the sole owner of loaded data. */
export class HttpTaskService implements TaskService {
  private writes = new Map<string, Promise<unknown>>();
  constructor(private readonly client: HttpTransport) {}

  async query({ query, sort, board, offset, limit = 50 }: TaskPageRequest): Promise<TaskPage> {
    const params = new URLSearchParams({ scope: query.scope, status: board ? "all" : query.status === "progress" ? "in_progress" : query.status });
    if (query.project !== "all") params.set("project_id", query.project);
    if (query.due !== "any") params.set("due", query.due);
    if (query.priority !== "any") params.set("priority", `P${query.priority}`);
    if (query.search.trim()) params.set("q", query.search.trim());
    if (query.signal) params.set("signal", ({ overdue: "overdue", critical: "p0_at_risk", soon: "due_soon", unassigned: "needs_owner" } as const)[query.signal]);
    params.set("sort", sort === "due" ? "due_date" : sort);
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    // The design's Attention strip describes open work in the project, independent of toolbar/scope.
    const summaryParams = new URLSearchParams(query.project === "all" ? {} : { project_id: query.project });
    const [page, summary, columnEntries] = await Promise.all([
      this.client.get<Schemas["TaskListResponse"]>(`/tasks?${params}`),
      this.client.get<Schemas["TaskSummaryResponse"]>(`/tasks/summary${summaryParams.size ? `?${summaryParams}` : ""}`),
      board ? Promise.all((["todo", "progress", "testing", "done"] as const).map(async (status) => {
        const countParams = new URLSearchParams(params);
        countParams.set("status", apiStatus(status)); countParams.set("limit", "1"); countParams.set("offset", "0");
        const count = await this.client.get<Schemas["TaskListResponse"]>(`/tasks?${countParams}`);
        return [status, count.total] as const;
      })) : Promise.resolve(null),
    ]);
    const columns = columnEntries ? Object.fromEntries(columnEntries) as Record<TaskStatus, number> : undefined;
    const headerTotal = columns ? query.status === "all" ? page.total : query.status === "open"
      ? columns.todo + columns.progress + columns.testing : columns[query.status] : page.total;
    let projectHasTasks: boolean | undefined;
    if (query.project !== "all") {
      projectHasTasks = (summary.projects.find((p) => p.id === query.project)?.open_tasks ?? 0) > 0;
      if (!projectHasTasks) {
        const existence = await this.client.get<Schemas["TaskListResponse"]>(`/tasks?${new URLSearchParams({ project_id: query.project, status: "all", limit: "1", offset: "0" })}`);
        projectHasTasks = existence.total > 0;
      }
    }
    return {
      tasks: page.items.map(taskFromApi), total: page.total, offset: page.offset, limit: page.limit, headerTotal, columns, projectHasTasks,
      sidebar: { ...summary.counts, byProject: Object.fromEntries(summary.projects.map((p) => [p.id, p.open_tasks])) },
      signals: { overdue: summary.signals.overdue, critical: summary.signals.p0_at_risk, soon: summary.signals.due_soon, unassigned: summary.signals.needs_owner },
    };
  }

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
