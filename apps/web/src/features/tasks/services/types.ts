import type { Attachment, Person, Project, ProjectTone, Task, TaskStatus } from "../model/types";

/** Returns the current time in epoch milliseconds. Injected so tests and screenshots are deterministic. */
export type Clock = () => number;

export const systemClock: Clock = () => Date.now();

export class TaskNotFoundError extends Error {
  constructor(id: string) {
    super(`Task ${id} does not exist.`);
    this.name = "TaskNotFoundError";
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
  list(): Promise<Task[]>;
  get(id: string): Promise<Task | null>;
  create(input: NewTask): Promise<Task>;
  /**
   * Plain edits are silent. An assignee change is logged as "Assigned to ..." / "Unassigned"
   * unless `note` is given, in which case the note is logged instead.
   */
  update(id: string, patch: TaskPatch, note?: string): Promise<Task>;
  /** Logs "Moved A → B". Moving to the current status changes nothing. */
  move(id: string, status: TaskStatus): Promise<Task>;
  /** Completes an open task; reopens a done one to To Do. */
  toggleDone(id: string): Promise<Task>;
  /** Blank text is ignored. */
  addStep(id: string, text: string): Promise<Task>;
  toggleStep(id: string, stepId: string): Promise<Task>;
  removeStep(id: string, stepId: string): Promise<Task>;
  /** Blank text is ignored. */
  addComment(id: string, text: string): Promise<Task>;
  /** Logs "Attached <name>". */
  addAttachment(id: string, attachment: Attachment): Promise<Task>;
  remove(id: string): Promise<void>;
}

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
}

export interface ProposedStep {
  id: string;
  text: string;
}

export type Generation =
  | { taskId: string; phase: "running" }
  | { taskId: string; phase: "proposed"; steps: ProposedStep[] };

/**
 * Drafts steps for a task. One generation is in flight at a time: it is `running`, then
 * `proposed` with steps the user can prune, then accepted into the task or discarded.
 * A generation never outlives its task: once the task is gone, `accept` and `discard` clear
 * it without touching anything else.
 */
export interface StepGenerationService {
  /** Starting the task that is already running is a no-op; another task replaces the run. */
  start(taskId: string): Promise<void>;
  current(): Generation | null;
  /** Calls `listener` on every change; returns the unsubscribe function. */
  subscribe(listener: (generation: Generation | null) => void): () => void;
  removeProposed(stepId: string): void;
  /** Appends the proposed steps to the task. Resolves to null unless a proposal is waiting. */
  accept(): Promise<Task | null>;
  discard(): Promise<void>;
}
