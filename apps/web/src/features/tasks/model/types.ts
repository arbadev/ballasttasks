/** The four workflow states, in board order. Ids match the design's and are stable. */
export type TaskStatus = "todo" | "progress" | "testing" | "done";

/** P0 (most urgent) to P3. */
export type Priority = 0 | 1 | 2 | 3;

/** A calendar day as YYYY-MM-DD, in the user's local time. Never carries a time of day. */
export type DueDate = string;

export interface Step {
  id: string;
  text: string;
  done: boolean;
}

export type AttachmentKind = "pdf" | "image" | "link";

export interface Attachment {
  kind: AttachmentKind;
  name: string;
  /** Secondary line: size and type for files, the host for links. */
  meta: string;
}

export type ActivityType = "log" | "comment";

export interface ActivityEntry {
  type: ActivityType;
  /** Person id of the author. */
  who: string;
  text: string;
  /** Epoch milliseconds. */
  at: number;
}

export interface Person {
  id: string;
  name: string;
  initials: string;
  role: string;
}

/** Which design token colours a project's dot. */
export type ProjectTone = "accent" | "muted" | "info" | "ok" | "warn";

export interface Project {
  id: string;
  name: string;
  /** A short code that identifies the project: 2 to 4 uppercase letters. */
  key?: string;
  tone: ProjectTone;
}

export interface Task {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  /** Project id. */
  project: string;
  /** Person id, or null while the task needs an owner. */
  assignee: string | null;
  due: DueDate | null;
  prio: Priority;
  /** 0 to 100. */
  importance: number;
  steps: Step[];
  attachments: Attachment[];
  activity: ActivityEntry[];
  /** Epoch milliseconds. */
  createdAt: number;
  /** Epoch milliseconds. */
  updatedAt: number;
}
