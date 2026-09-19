import type { components } from "@/lib/api/schema";
import type { Attachment, Person, Project, ProjectTone, Task, TaskStatus } from "../model/types";
export type Schemas = components["schemas"];

export const apiStatus = (status: TaskStatus): Schemas["TaskStatus"] => status === "progress" ? "in_progress" : status;
export const personFromApi = (person: Schemas["PersonResponse"]): Person => ({ id: person.id, name: person.full_name, initials: person.initials, role: person.role_label ?? "" });
const tones: Record<string, ProjectTone> = { acc: "accent", accent: "accent", muted: "muted", info: "info", ok: "ok", warn: "warn" };
export const projectFromApi = (project: Schemas["ProjectResponse"]): Project => ({ id: project.id, key: project.key, name: project.name, tone: tones[project.color ?? "muted"] ?? "muted" });
export const attachmentFromApi = (attachment: Schemas["AttachmentResponse"]): Attachment => ({
  id: attachment.id, kind: attachment.kind, name: attachment.name,
  url: attachment.url ?? undefined, contentType: attachment.content_type ?? undefined, sizeBytes: attachment.size_bytes ?? undefined,
  meta: attachment.url ? new URL(attachment.url).host : `${((attachment.size_bytes ?? 0) / 1024).toFixed(1)} KB · ${attachment.content_type ?? attachment.kind}`,
});

export function taskFromApi(row: Schemas["TaskResponse"]): Task {
  return {
    id: row.id, key: row.key, title: row.title, description: row.description ?? "",
    status: row.status === "in_progress" ? "progress" : row.status,
    project: row.project_id, due: row.due_date, assignee: row.assignee_id,
    prio: ({ P0: 0, P1: 1, P2: 2, P3: 3 } as const)[row.priority], importance: row.importance,
    createdAt: Date.parse(row.created_at), updatedAt: Date.parse(row.updated_at),
    steps: [], attachments: [], activity: [], detailLoaded: false,
    tally: { steps: row.steps_total, done: row.steps_done, attachments: row.attachments_count, comments: row.comments_count },
  };
}
