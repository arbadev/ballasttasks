import { describe, expect, it } from "vitest";
import { NOW, due, makeTask } from "@/test/tasks";
import { sidebarCounts } from "./counts";

describe("sidebarCounts", () => {
  const tasks = [
    makeTask({ id: "a", due: due(-2) }),
    makeTask({ id: "b", assignee: "lm", due: due(3) }),
    makeTask({ id: "c", project: "inbox", assignee: null }),
    makeTask({ id: "d", status: "done", due: due(-9) }),
  ];

  it("counts open tasks only: all, mine, overdue and per project", () => {
    expect(sidebarCounts(tasks, { now: NOW, currentUserId: "ab" })).toEqual({
      all: 3,
      mine: 1,
      overdue: 1,
      byProject: { ballast: 2, inbox: 1 },
    });
  });

  it("is all zeroes for an empty workspace", () => {
    expect(sidebarCounts([], { now: NOW, currentUserId: "ab" })).toEqual({ all: 0, mine: 0, overdue: 0, byProject: {} });
  });
});
