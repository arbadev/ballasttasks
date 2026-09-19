import { describe, expect, it } from "vitest";
import { NOW, due, makeTask } from "@/test/tasks";
import { attentionSignals } from "./signals";

const tasks = [
  makeTask({ id: "late", due: due(-2), prio: 1 }),
  makeTask({ id: "risk1", due: due(4), prio: 0, assignee: null }),
  makeTask({ id: "risk2", due: due(3), prio: 0 }),
  makeTask({ id: "today", project: "inbox", due: due(0), prio: 1 }),
  makeTask({ id: "soon", status: "testing", due: due(1) }),
  makeTask({ id: "orphan", assignee: null }),
  makeTask({ id: "shipped", status: "done", due: due(-6), prio: 0, assignee: null }),
];

describe("attentionSignals", () => {
  it("counts each signal over the open tasks", () => {
    expect(attentionSignals(tasks, { now: NOW, project: "all", active: null })).toEqual([
      { id: "overdue", label: "overdue", count: 1, tone: "danger", blink: false, active: false },
      { id: "critical", label: "P0 at risk", count: 2, tone: "danger", blink: true, active: false },
      { id: "soon", label: "due soon", count: 4, tone: "warn", blink: false, active: false },
      { id: "unassigned", label: "need an owner", count: 2, tone: "info", blink: false, active: false },
    ]);
  });

  it("follows the selected project but not the scope", () => {
    const signals = attentionSignals(tasks, { now: NOW, project: "inbox", active: null });
    expect(signals.map((s) => [s.id, s.count])).toEqual([["soon", 1]]);
  });

  it("uses the singular label for exactly one task", () => {
    const one = attentionSignals([makeTask({ assignee: null })], { now: NOW, project: "all", active: null });
    expect(one).toEqual([{ id: "unassigned", label: "needs an owner", count: 1, tone: "info", blink: false, active: false }]);
  });

  it("hides empty signals, except the active one so it can still be switched off", () => {
    const signals = attentionSignals([makeTask()], { now: NOW, project: "all", active: "overdue" });
    expect(signals).toEqual([{ id: "overdue", label: "overdue", count: 0, tone: "danger", blink: false, active: true }]);
  });

  it("is empty when nothing needs attention", () => {
    expect(attentionSignals([makeTask()], { now: NOW, project: "all", active: null })).toEqual([]);
  });
});
