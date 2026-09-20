import type { Attachment, Person, Project, ProjectTone, Task, TaskStatus } from "../model/types";
import type { TaskPage, TaskPageRequest } from "./query";

/** Returns the current time in epoch milliseconds. Injected so tests and screenshots are deterministic. */
export type Clock = () => number;

export const systemClock: Clock = () => Date.now();

export class TaskNotFoundError extends Error {
  constructor(id: string) {
    super(`Task ${id} does not exist.`);
    this.name = "TaskNotFoundError";
  }
}

/** The row a composer append created: which task, which box, and the id the server gave it. */
export interface AcknowledgedWrite {
  taskId: string;
  kind: "comment" | "step";
  childId: string;
}

/**
 * A composer write was acknowledged, but its canonical read failed. Never resend it: `saved`
 * names the row the server stored, so seeing that row is what ends the recovery.
 */
export class TaskReadbackError extends Error {
  constructor(readonly saved: AcknowledgedWrite) {
    super("The change was saved, but the task could not be reloaded.");
    this.name = "TaskReadbackError";
  }
}

export interface NewTask {
  title: string;
  /** Defaults to To Do. */
  status?: TaskStatus;
  /** Defaults to the Inbox. */
  project?: string;
}

export type TaskPatch = Partial<Pick<Task, "title" | "description" | "assignee" | "due" | "prio" | "importance" | "project">>;

/**
 * Everything the UI does to tasks. Every mutation resolves to the task as it now is, so the
 * caller can replace its copy; tasks are immutable values and are never changed in place.
 * Mutations on an unknown id reject with TaskNotFoundError.
 */
export interface TaskService {
  /** Legacy complete-list capability for explicit demo/test consumers. */
  list(): Promise<Task[]>;
  /** Real workspace queries and pages on the server; never treats a page as the complete list. */
  query?(request: TaskPageRequest): Promise<TaskPage>;
  get(id: string): Promise<Task | null>;
  /** Read-only recovery ordered after outstanding writes; older adapters may use get. */
  refresh?(id: string): Promise<Task | null>;
  create(input: NewTask): Promise<Task>;
  /**
   * The server owns activity wording: assignment, due-date and priority changes log events.
   * `note` is a deprecated caller hint, never a custom event or comment.
   */
  update(id: string, patch: TaskPatch, note?: string): Promise<Task>;
  /** Logs "Moved A → B". Moving to the current status changes nothing. */
  move(id: string, status: TaskStatus): Promise<Task>;
  /** Completes an open task; reopens a done one to To Do. */
  toggleDone(id: string): Promise<Task>;
  /** Blank text is ignored. TaskReadbackError means saved: recover by reading, never re-add. */
  addStep(id: string, text: string): Promise<Task>;
  /** Renames in place (trimmed 1–200 characters, no NUL); silent activity. */
  renameStep(id: string, stepId: string, text: string): Promise<Task>;
  /** Exact permutation of current IDs; stale membership rejects the whole operation. */
  reorderSteps(id: string, stepIds: string[]): Promise<Task>;
  toggleStep(id: string, stepId: string): Promise<Task>;
  removeStep(id: string, stepId: string): Promise<Task>;
  /** Blank text is ignored. TaskReadbackError means saved: recover by reading, never re-post. */
  addComment(id: string, text: string): Promise<Task>;
  /** Logs "Attached <name>". File-capable adapters receive the original bytes, not metadata alone. */
  addAttachment(id: string, attachment: Attachment, file?: File): Promise<Task>;
  /** Optional only for older demo/test adapters; HTTP implements all storage operations. */
  uploadAttachment?(id: string, file: File): Promise<Task>;
  downloadAttachment?(id: string, attachmentId: string): Promise<Blob>;
  removeAttachment?(id: string, attachmentId: string): Promise<Task>;
  acceptSteps?(id: string, titles: string[]): Promise<Task>;
  remove(id: string): Promise<void>;
}

/** What the editor changed: an absent field is left as it is stored. */
export type ProjectEdit = Partial<Pick<NewProject, "name" | "tone">>;

export interface NewProject {
  name: string;
  /** 2 to 4 uppercase letters, unique among the projects. */
  key: string;
  tone: ProjectTone;
}

/** A message per field that was refused; the UI shows each next to its input. */
export type ProjectFieldErrors = Partial<Record<"name" | "key", string>>;

/** The directory refused a new project because of what was entered, not because it failed. */
export class ProjectRejectedError extends Error {
  constructor(readonly errors: ProjectFieldErrors) {
    super(Object.values(errors).join(" "));
    this.name = "ProjectRejectedError";
  }
}

export interface DirectoryService {
  people(): Promise<Person[]>;
  projects(): Promise<Project[]>;
  currentUser(): Promise<Person>;
  /**
   * Resolves to the stored project, which `projects()` lists from then on. Rejects with
   * ProjectRejectedError when the name or key breaks a rule (see features/projects/model).
   */
  createProject(input: NewProject): Promise<Project>;
  /** Applies the fields the edit carries and leaves the rest, including the key, alone. */
  updateProject(id: string, input: ProjectEdit): Promise<Project>;
}

export interface ProposedStep {
  id: string;
  text: string;
}

export type Generation =
  | { taskId: string; phase: "running"; notice?: string }
  | { taskId: string; phase: "proposed"; steps: ProposedStep[]; accepting?: boolean; notice?: string }
  | { taskId: string; phase: "error"; message: string; recovery?: "reload" };

/**
 * Drafts are proposals only. HTTP handles belong to tasks and survive changing selection;
 * current() observes the selected task. Acceptance is one atomic bulk operation.
 * Discard is local only: it does not cancel a server job.
 */
export interface StepGenerationService {
  /** Starts a new independent job; UI disables repeated submission while pending. */
  start(taskId: string): Promise<void>;
  current(): Generation | null;
  /** Calls `listener` on every change; returns the unsubscribe function. */
  subscribe(listener: (generation: Generation | null) => void): () => void;
  removeProposed(stepId: string): void;
  /** Appends the proposed steps to the task. Resolves to null unless a proposal is waiting. */
  accept(): Promise<Task | null>;
  discard(): Promise<void>;
  /** Additive observation/lifetime seams; older explicit demo doubles may omit them. */
  select?(taskId: string | null): void;
  setVisible?(visible: boolean): void;
  forget?(taskId: string): void;
  dispose?(): void;
}
