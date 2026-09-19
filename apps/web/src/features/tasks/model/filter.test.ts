import { describe, expect, it } from "vitest";
import { NOW, due, makeTask } from "@/test/tasks";
import { DEFAULT_QUERY, filterTasks, selectTasks, sortTasks, type TaskQuery } from "./filter";

const ME = "ab";
const tasks = [
  makeTask({ id: "late", title: "Write the PRD", due: due(-2), prio: 1, importance: 75 }),
  makeTask({ id: "risk", title: "JWT authentication", description: "access + refresh tokens", due: due(4), prio: 0, importance: 90, assignee: null }),
  makeTask({ id: "today", title: "Confirm the slot", project: "inbox", due: due(0), prio: 1, importance: 70 }),
  makeTask({ id: "soon", title: "Docker compose", status: "testing", due: due(1), prio: 2, importance: 50, assignee: "tr" }),
  makeTask({ id: "later", title: "Seed data", due: due(8), prio: 1, importance: 70, assignee: "lm", updatedAt: NOW - 1000 }),
  makeTask({ id: "undated", title: "Rate limiting", status: "progress", prio: 2, importance: 55, assignee: null }),
  makeTask({ id: "shipped", title: "Health endpoints", status: "done", due: due(-6), prio: 0, importance: 90 }),
];

const ids = (query: Partial<TaskQuery>, applyStatus = true) =>
  filterTasks(tasks, { ...DEFAULT_QUERY, ...query }, { now: NOW, currentUserId: ME, applyStatus })
    .map((t) => t.id)
    .sort();

describe("filterTasks", () => {
  it("shows every open task by default", () => {
    expect(ids({})).toEqual(["late", "later", "risk", "soon", "today", "undated"]);
  });

  it("scopes to the current user's tasks", () => {
    expect(ids({ scope: "mine" })).toEqual(["late", "today"]);
  });

  it("scopes to overdue open tasks, never done ones", () => {
    expect(ids({ scope: "overdue", status: "all" })).toEqual(["late"]);
  });

  it("filters by project", () => {
    expect(ids({ project: "inbox" })).toEqual(["today"]);
  });

  it("filters by a single status", () => {
    expect(ids({ status: "testing" })).toEqual(["soon"]);
    expect(ids({ status: "done" })).toEqual(["shipped"]);
  });

  it("shows done tasks too under Everything", () => {
    expect(ids({ status: "all" })).toHaveLength(7);
  });

  it("ignores the status filter when asked to, as the board does", () => {
    expect(ids({ status: "testing" }, false)).toHaveLength(7);
  });

  it("filters by due date", () => {
    expect(ids({ due: "overdue", status: "all" })).toEqual(["late"]);
    expect(ids({ due: "today" })).toEqual(["today"]);
    expect(ids({ due: "week" })).toEqual(["risk", "soon", "today"]);
    expect(ids({ due: "none" })).toEqual(["undated"]);
  });

  it("filters by priority", () => {
    expect(ids({ priority: "0" })).toEqual(["risk"]);
    expect(ids({ priority: "2" })).toEqual(["soon", "undated"]);
  });

  it("searches title and description, ignoring case and surrounding space", () => {
    expect(ids({ search: "  jwt " })).toEqual(["risk"]);
    expect(ids({ search: "REFRESH" })).toEqual(["risk"]);
    expect(ids({ search: "nothing like this" })).toEqual([]);
  });

  it("narrows to an Attention signal", () => {
    expect(ids({ signal: "overdue" })).toEqual(["late"]);
    expect(ids({ signal: "critical" })).toEqual(["risk"]);
    expect(ids({ signal: "soon" })).toEqual(["risk", "soon", "today"]);
    expect(ids({ signal: "unassigned" })).toEqual(["risk", "undated"]);
  });

  it("combines filters", () => {
    expect(ids({ scope: "mine", project: "inbox", priority: "1" })).toEqual(["today"]);
    expect(ids({ scope: "mine", signal: "unassigned" })).toEqual([]);
  });
});

describe("sortTasks", () => {
  const order = (sort: Parameters<typeof sortTasks>[1]) => sortTasks(tasks, sort, NOW).map((t) => t.id);

  it("sorts by urgency score, most urgent first", () => {
    expect(order("urgency")).toEqual(["late", "risk", "today", "soon", "later", "undated", "shipped"]);
  });

  it("sorts by importance", () => {
    expect(order("importance")).toEqual(["risk", "shipped", "late", "today", "later", "undated", "soon"]);
  });

  it("sorts by due date, undated last, importance breaking ties", () => {
    expect(order("due")).toEqual(["shipped", "late", "today", "soon", "risk", "later", "undated"]);
  });

  it("sorts by most recently updated", () => {
    expect(order("updated")[0]).toBe("later");
  });

  it("does not mutate its input", () => {
    const before = tasks.map((t) => t.id);
    sortTasks(tasks, "importance", NOW);
    expect(tasks.map((t) => t.id)).toEqual(before);
  });
});

describe("selectTasks", () => {
  it("filters, then sorts", () => {
    const result = selectTasks(tasks, { ...DEFAULT_QUERY, scope: "mine" }, "importance", { now: NOW, currentUserId: ME });
    expect(result.map((t) => t.id)).toEqual(["late", "today"]);
  });
});
