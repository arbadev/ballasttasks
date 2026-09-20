import type { components } from "@/lib/api/schema";
type Schemas = components["schemas"];
export const apiTask = (patch: Partial<Schemas["TaskDetailResponse"]> = {}): Schemas["TaskDetailResponse"] => ({
  id: "task-id", key: "IN-01", project_id: "project-id", title: "Real task", description: null,
  status: "todo", due_date: null, assignee_id: null, created_by: "user-id",
  created_at: "2026-09-19T00:00:00Z", updated_at: "2026-09-19T00:00:00Z", completed_at: null,
  priority: "P2", importance: 50, steps_total: 0, steps_done: 0, comments_count: 0, attachments_count: 0,
  attention: { is_overdue: false, is_due_soon: false, is_p0_at_risk: false, needs_owner: true, days_until_due: null, urgency: 0, reasons: ["needs_owner"] },
  steps: [], attachments: [], ...patch,
});
export const apiPerson = { id: "user-id", full_name: "Test Person", initials: "TP", role_label: null };
export const apiProject = { id: "project-id", name: "Inbox", key: "IN", color: "acc", open_tasks: 1, created_at: "2026-09-19T00:00:00Z", updated_at: "2026-09-19T00:00:00Z" };

/** A `TaskListResponse`: `status_totals` counts every matching task, so pass them for a truncated page. */
export const apiTaskPage = (
  items: Schemas["TaskResponse"][],
  page: { total?: number; limit?: number; offset?: number; statusTotals?: Partial<Schemas["StatusTotalsResponse"]> } = {},
): Schemas["TaskListResponse"] => {
  const counted: Schemas["StatusTotalsResponse"] = { todo: 0, in_progress: 0, testing: 0, done: 0 };
  for (const item of items) counted[item.status] += 1;
  return {
    items,
    total: page.total ?? items.length,
    limit: page.limit ?? 50,
    offset: page.offset ?? 0,
    status_totals: { ...counted, ...page.statusTotals },
  };
};
