import { describe, expect, it } from "vitest";
import { NOW, due, makeTask } from "@/test/tasks";
import { urgency } from "./urgency";

describe("urgency", () => {
  it("scores an overdue task highest, by how late it is", () => {
    const u = urgency(makeTask({ due: due(-2), prio: 1, importance: 75 }), NOW);
    expect(u).toMatchObject({ open: true, overdue: true, today: false, soon: false, critical: false, diff: -2 });
    expect(u.score).toBe(1000 + 20 + 7.5 + 6);
  });

  it("caps the lateness bonus at 30 days", () => {
    expect(urgency(makeTask({ due: due(-45), prio: 3, importance: 0 }), NOW).score).toBe(1300);
  });

  it("treats a P0 inside its widened window as critical", () => {
    // P0 widens the 2-day soon window by 2, so a P0 due in 3 days is at risk.
    const u = urgency(makeTask({ due: due(3), prio: 0, importance: 95 }), NOW);
    expect(u).toMatchObject({ critical: true, soon: true, overdue: false, blink: true });
    expect(u.score).toBe(800 + 10 + 9.5 + 9);
  });

  it("adds the needs-an-owner bonus to an unassigned open task", () => {
    const u = urgency(makeTask({ due: due(4), prio: 0, importance: 90, assignee: null }), NOW);
    expect(u).toMatchObject({ critical: true, unassigned: true });
    expect(u.score).toBe(800 + 0 + 40 + 9 + 9);
  });

  it("scores a task due today", () => {
    const u = urgency(makeTask({ due: due(0), prio: 1, importance: 70 }), NOW);
    expect(u).toMatchObject({ today: true, soon: false, critical: false, blink: false });
    expect(u.score).toBe(600 + 7 + 6);
  });

  it("scores a task due soon, with P1 widening the window by one day", () => {
    expect(urgency(makeTask({ due: due(1), prio: 2, importance: 50 }), NOW)).toMatchObject({ soon: true, score: 400 + 10 + 5 + 3 });
    expect(urgency(makeTask({ due: due(3), prio: 1 }), NOW).soon).toBe(true);
    expect(urgency(makeTask({ due: due(3), prio: 2 }), NOW).soon).toBe(false);
  });

  it("decays the score of a later task with distance, never below the base", () => {
    expect(urgency(makeTask({ due: due(4), prio: 1, importance: 65 }), NOW).score).toBe(180 + 6.5 + 6);
    expect(urgency(makeTask({ due: due(60), prio: 3, importance: 0 }), NOW).score).toBe(0);
  });

  it("gives an undated task only its importance and priority weight", () => {
    const u = urgency(makeTask({ prio: 3, importance: 30 }), NOW);
    expect(u).toMatchObject({ overdue: false, today: false, soon: false, critical: false, diff: Infinity });
    expect(u.score).toBe(3);
  });

  it("never flags a done task, however late it was", () => {
    const u = urgency(makeTask({ status: "done", due: due(-6), prio: 0, importance: 90, assignee: null }), NOW);
    expect(u).toMatchObject({ open: false, overdue: false, critical: false, unassigned: false, blink: false });
    expect(u.score).toBe(9 + 9);
  });

  it("blinks only for a P0 that is overdue or at risk", () => {
    expect(urgency(makeTask({ due: due(-1), prio: 0 }), NOW).blink).toBe(true);
    expect(urgency(makeTask({ due: due(-1), prio: 1 }), NOW).blink).toBe(false);
    expect(urgency(makeTask({ due: due(9), prio: 0 }), NOW).blink).toBe(false);
  });

  it("honours a custom soon window and clamps a negative one to zero", () => {
    expect(urgency(makeTask({ due: due(5), prio: 2 }), NOW, 5).soon).toBe(true);
    expect(urgency(makeTask({ due: due(1), prio: 2 }), NOW, -3).soon).toBe(false);
  });
});
