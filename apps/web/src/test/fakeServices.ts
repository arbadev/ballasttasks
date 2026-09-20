import type { SignalId } from "@/features/tasks/model/filter";
import { selectTasks } from "@/features/tasks/model/filter";
import { sidebarCounts } from "@/features/tasks/model/counts";
import { attentionSignals } from "@/features/tasks/model/signals";
import { STATUSES } from "@/features/tasks/model/statuses";
import type { Attachment, Person, Project, Task, TaskStatus } from "@/features/tasks/model/types";
import type { TaskPage, TaskPageRequest } from "@/features/tasks/services/query";
import { SEED_PEOPLE, SEED_PROJECTS } from "@/features/tasks/services/seed";
import {
  TaskNotFoundError,
  type DirectoryService,
  type Generation,
  type NewProject,
  type NewTask,
  type ProjectEdit,
  type StepGenerationService,
  type TaskPatch,
  type TaskService,
} from "@/features/tasks/services/types";
import { renameStep, reorderSteps } from "@/features/tasks/model/stepEditing";
import { NOW } from "./tasks";

/** The calls a test can keep a server from answering, one call each. */
type HeldCall = "update" | "move" | "query";

/** A TaskService over a plain array that records every call, for tests that drive the UI. */
export class FakeTaskService implements TaskService {
  readonly calls: unknown[][] = [];
  protected tasks: Task[];
  private sequence = 0;
  private readonly gates = new Map<HeldCall, Promise<void>>();

  constructor(tasks: Task[] = []) {
    this.tasks = [...tasks];
  }

  /** Makes the next `call` wait, as a server that has taken the request but not answered yet. */
  holdNext(call: HeldCall) {
    let release!: () => void;
    let fail!: (error: Error) => void;
    this.gates.set(call, new Promise<void>((resolve, reject) => {
      release = resolve;
      fail = reject;
    }));
    return { release, fail };
  }

  /** Waits for the gate a test put on `call`, if there is one. */
  protected async awaitHold(call: HeldCall) {
    const gate = this.gates.get(call);
    if (!gate) return;
    this.gates.delete(call);
    await gate;
  }

  private change(id: string, fn: (t: Task) => Task): Task {
    const found = this.tasks.find((t) => t.id === id);
    if (!found) throw new TaskNotFoundError(id);
    const next = fn(found);
    this.tasks = this.tasks.map((t) => (t.id === id ? next : t));
    return next;
  }

  async list() {
    this.calls.push(["list"]);
    return [...this.tasks];
  }
  async get(id: string) {
    return this.tasks.find((t) => t.id === id) ?? null;
  }
  async create(input: NewTask) {
    this.calls.push(["create", input]);
    const task: Task = {
      id: `new${++this.sequence}`, title: input.title, description: "", status: input.status ?? "todo", project: input.project ?? "inbox",
      assignee: null, due: null, prio: 2, importance: 50, steps: [], attachments: [], activity: [], createdAt: NOW, updatedAt: NOW,
    };
    this.tasks = [task, ...this.tasks];
    return task;
  }
  async update(id: string, patch: TaskPatch, note?: string) {
    this.calls.push(note === undefined ? ["update", id, patch] : ["update", id, patch, note]);
    await this.awaitHold("update");
    return this.change(id, (t) => ({ ...t, ...patch }));
  }
  async move(id: string, status: TaskStatus) {
    this.calls.push(["move", id, status]);
    await this.awaitHold("move");
    return this.change(id, (t) => ({ ...t, status }));
  }
  async toggleDone(id: string) {
    this.calls.push(["toggleDone", id]);
    return this.change(id, (t) => ({ ...t, status: t.status === "done" ? "todo" : "done" }));
  }
  async addStep(id: string, text: string) {
    this.calls.push(["addStep", id, text]);
    return this.change(id, (t) => ({ ...t, steps: [...t.steps, { id: `step${++this.sequence}`, text, done: false }] }));
  }
  async renameStep(id: string, stepId: string, text: string) {
    this.calls.push(["renameStep", id, stepId, text]);
    return this.change(id, (t) => ({ ...t, steps: renameStep(t.steps, stepId, text) }));
  }
  async reorderSteps(id: string, stepIds: string[]) {
    this.calls.push(["reorderSteps", id, stepIds]);
    return this.change(id, (t) => ({ ...t, steps: reorderSteps(t.steps, stepIds) }));
  }
  async toggleStep(id: string, stepId: string) {
    this.calls.push(["toggleStep", id, stepId]);
    return this.change(id, (t) => ({ ...t, steps: t.steps.map((s) => (s.id === stepId ? { ...s, done: !s.done } : s)) }));
  }
  async removeStep(id: string, stepId: string) {
    this.calls.push(["removeStep", id, stepId]);
    return this.change(id, (t) => ({ ...t, steps: t.steps.filter((s) => s.id !== stepId) }));
  }
  async addComment(id: string, text: string) {
    this.calls.push(["addComment", id, text]);
    return this.change(id, (t) => ({ ...t, activity: [...t.activity, { type: "comment", who: "ab", text, at: NOW }] }));
  }
  async addAttachment(id: string, attachment: Attachment) {
    this.calls.push(["addAttachment", id, attachment]);
    return this.change(id, (t) => ({ ...t, attachments: [...t.attachments, attachment] }));
  }
  async remove(id: string) {
    this.calls.push(["remove", id]);
    this.tasks = this.tasks.filter((t) => t.id !== id);
  }
}

/**
 * The same fake, serving pages as the HTTP adapter does: the workspace then holds a page
 * instead of the complete list, and every save is followed by a canonical query over it.
 */
export class FakeQueryTaskService extends FakeTaskService {
  async query(request: TaskPageRequest): Promise<TaskPage> {
    this.calls.push(["query", request]);
    await this.awaitHold("query");
    const context = { now: NOW, currentUserId: SEED_PEOPLE[0].id };
    const listed = selectTasks(this.tasks, request.query, request.sort, context);
    const shown = request.board ? selectTasks(this.tasks, request.query, request.sort, { ...context, applyStatus: false }) : listed;
    const limit = request.limit ?? 50;
    const signals = { overdue: 0, critical: 0, soon: 0, unassigned: 0 } as Record<SignalId, number>;
    for (const signal of attentionSignals(this.tasks, { now: NOW, project: request.query.project, active: null })) signals[signal.id] = signal.count;
    return {
      tasks: shown.slice(request.offset, request.offset + limit),
      total: shown.length,
      headerTotal: listed.length,
      offset: request.offset,
      limit,
      sidebar: sidebarCounts(this.tasks, context),
      signals,
      columns: Object.fromEntries(STATUSES.map((status) => [status.id, shown.filter((t) => t.status === status.id).length])) as Record<TaskStatus, number>,
      projectHasTasks: request.query.project === "all" ? undefined : this.tasks.some((t) => t.project === request.query.project),
    };
  }
}

export class FakeDirectoryService implements DirectoryService {
  readonly calls: unknown[][] = [];
  private readonly created: Project[] = [];
  private readonly edited = new Map<string, Project>();
  private gate: Promise<void> | null = null;

  constructor(
    private readonly data: { people?: Person[]; projects?: Project[] } = {},
  ) {}
  async people() {
    return this.data.people ?? [...SEED_PEOPLE];
  }
  async projects() {
    return [...(this.data.projects ?? SEED_PROJECTS), ...this.created].map((project) => this.edited.get(project.id) ?? project);
  }
  async currentUser() {
    return (this.data.people ?? SEED_PEOPLE)[0];
  }
  /** Makes the next `createProject` wait until the test releases or fails it. */
  holdNextCreate() {
    let release!: () => void;
    let fail!: (error: Error) => void;
    this.gate = new Promise<void>((resolve, reject) => {
      release = resolve;
      fail = reject;
    });
    return { release, fail };
  }
  async updateProject(id: string, input: ProjectEdit) {
    this.calls.push(["updateProject", id, input]);
    const gate = this.gate;
    this.gate = null;
    if (gate) await gate;
    const project = (await this.projects()).find((item) => item.id === id);
    if (!project) throw new Error("Project not found.");
    const saved = { ...project, ...(input.name !== undefined && { name: input.name }), ...(input.tone !== undefined && { tone: input.tone }) };
    this.edited.set(id, saved);
    return saved;
  }
  /** Stores whatever it is given: the rules are the model's, tested there. */
  async createProject(input: NewProject) {
    this.calls.push(["createProject", input]);
    const gate = this.gate;
    this.gate = null;
    if (gate) await gate;
    const project: Project = { id: `p${this.created.length + 1}`, ...input };
    this.created.push(project);
    return project;
  }
}

/** A StepGenerationService the test drives by hand with `emit`. */
export class FakeStepGenerationService implements StepGenerationService {
  readonly calls: unknown[][] = [];
  private generation: Generation | null = null;
  private readonly listeners = new Set<(g: Generation | null) => void>();

  emit(generation: Generation | null) {
    this.generation = generation;
    this.listeners.forEach((l) => l(generation));
  }
  async start(taskId: string) {
    this.calls.push(["start", taskId]);
    this.emit({ taskId, phase: "running" });
  }
  current() {
    return this.generation;
  }
  subscribe(listener: (g: Generation | null) => void) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
  removeProposed(stepId: string) {
    this.calls.push(["removeProposed", stepId]);
  }
  async accept() {
    this.calls.push(["accept"]);
    this.emit(null);
    return null;
  }
  async discard() {
    this.calls.push(["discard"]);
    this.emit(null);
  }
}
