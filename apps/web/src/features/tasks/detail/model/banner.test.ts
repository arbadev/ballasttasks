import { describe, expect, it } from "vitest";
import { NOW, due, makeTask } from "@/test/tasks";
import { bannerFor } from "./banner";

describe("bannerFor", () => {
  it("is absent for a calm task: assigned, no near date", () => {
    expect(bannerFor(makeTask({ due: due(20) }), NOW, false)).toBeNull();
  });

  it("is absent for a done task, however late", () => {
    expect(bannerFor(makeTask({ status: "done", due: due(-4), assignee: null }), NOW, false)).toBeNull();
  });

  it("counts the days overdue, in the singular and the plural", () => {
    expect(bannerFor(makeTask({ due: due(-1) }), NOW, false)).toMatchObject({ text: "Overdue by 1 day", tone: "danger", canReschedule: true });
    expect(bannerFor(makeTask({ due: due(-3) }), NOW, false)?.text).toBe("Overdue by 3 days");
  });

  it("flags a P0 inside its window as at risk, and blinks", () => {
    expect(bannerFor(makeTask({ prio: 0, due: due(4) }), NOW, false)).toMatchObject({ text: "P0 due in 4 days", tone: "danger", blink: true });
    expect(bannerFor(makeTask({ prio: 0, due: due(1) }), NOW, false)?.text).toBe("P0 due in 1 day");
    expect(bannerFor(makeTask({ prio: 0, due: due(0) }), NOW, false)?.text).toBe("P0 due today");
  });

  it("warns about today and the soon window", () => {
    expect(bannerFor(makeTask({ due: due(0) }), NOW, false)).toMatchObject({ text: "Due today", tone: "warn", blink: false });
    expect(bannerFor(makeTask({ due: due(2) }), NOW, false)).toMatchObject({ text: "Due in 2 days", tone: "warn" });
    expect(bannerFor(makeTask({ due: due(1) }), NOW, false)?.text).toBe("Due in 1 day");
  });

  it("asks for an owner, alone in the info tone or appended to a date warning", () => {
    expect(bannerFor(makeTask({ assignee: null }), NOW, false)).toMatchObject({ text: "Needs an owner", tone: "info", canAssign: true, canReschedule: false });
    expect(bannerFor(makeTask({ assignee: null, due: due(-2) }), NOW, false)).toMatchObject({ text: "Overdue by 2 days · needs an owner", tone: "danger", canAssign: true });
  });

  it("offers to draft steps only for an overdue or at-risk task with no steps and no generation", () => {
    const hot = makeTask({ prio: 0, due: due(2) });
    expect(bannerFor(hot, NOW, false)?.canDraft).toBe(true);
    expect(bannerFor(hot, NOW, true)?.canDraft).toBe(false);
    expect(bannerFor({ ...hot, steps: [{ id: "s1", text: "x", done: false }] }, NOW, false)?.canDraft).toBe(false);
    expect(bannerFor(makeTask({ due: due(1) }), NOW, false)?.canDraft).toBe(false);
  });
});
