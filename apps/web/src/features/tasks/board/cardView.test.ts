import { describe, expect, it } from "vitest";
import { NOW, due, makeTask } from "@/test/tasks";
import { cardView, ENTRANCE_STEP_MS, entranceDelay } from "./cardView";

describe("cardView: due chip", () => {
  it("is quiet, with the calendar mark, for a date outside the soon window", () => {
    const view = cardView(makeTask({ due: due(9), prio: 2 }), NOW);
    expect(view.dueLabel).toBe("Due Sep 27");
    expect(view.dueTone).toBeNull();
    expect(view.dueMark).toBe("later");
    expect(view.rail).toBeNull();
  });

  it("says No date without one", () => {
    const view = cardView(makeTask({ due: null }), NOW);
    expect(view.dueLabel).toBe("No date");
    expect(view.dueMark).toBe("later");
  });

  it("warns, with the clock mark, when due today or soon", () => {
    const today = cardView(makeTask({ due: due(0), prio: 2 }), NOW);
    expect(today).toMatchObject({ dueLabel: "Due today", dueTone: "warn", dueMark: "soon", rail: "warn" });
    const soon = cardView(makeTask({ due: due(2), prio: 2 }), NOW);
    expect(soon).toMatchObject({ dueTone: "warn", dueMark: "soon", rail: "warn" });
  });

  it("is in danger, with the alert mark, when overdue", () => {
    const view = cardView(makeTask({ due: due(-2), prio: 1 }), NOW);
    expect(view).toMatchObject({ dueLabel: "Overdue · 2d", dueTone: "danger", dueMark: "overdue", rail: "danger", blink: false });
  });

  it("shows a done task's plain date with no urgency", () => {
    const view = cardView(makeTask({ status: "done", due: due(-6), prio: 0 }), NOW);
    expect(view).toMatchObject({ done: true, dueLabel: "Sep 12", dueTone: null, dueMark: "later", rail: null, blink: false });
  });
});

describe("cardView: priority mark", () => {
  it("uses one tone per priority", () => {
    const tones = ([0, 1, 2, 3] as const).map((prio) => cardView(makeTask({ prio, due: due(20) }), NOW).prioTone);
    expect(tones).toEqual(["p0", "p1", "p2", "p3"]);
    expect(cardView(makeTask({ prio: 1 }), NOW).prioLabel).toBe("P1");
  });

  it("turns hot, with a blinking danger rail, for a P0 at risk", () => {
    // P0 widens the soon window to four days.
    const view = cardView(makeTask({ prio: 0, due: due(4) }), NOW);
    expect(view).toMatchObject({ prioTone: "hot", rail: "danger", blink: true, dueTone: "warn", dueMark: "soon" });
  });

  it("turns hot for an overdue P0", () => {
    expect(cardView(makeTask({ prio: 0, due: due(-1) }), NOW)).toMatchObject({ prioTone: "hot", rail: "danger", blink: true });
  });
});

describe("cardView: counts and owner", () => {
  it("labels step progress and attachments only when there are any", () => {
    const empty = cardView(makeTask(), NOW);
    expect(empty.stepsLabel).toBeNull();
    expect(empty.attachmentsLabel).toBeNull();

    const view = cardView(
      makeTask({
        steps: [
          { id: "a", text: "one", done: true },
          { id: "b", text: "two", done: false },
        ],
        attachments: [{ kind: "link", name: "Docs", meta: "example.com" }],
      }),
      NOW,
    );
    expect(view.stepsLabel).toBe("1/2");
    expect(view.attachmentsLabel).toBe("1");
  });

  it("flags an open task without an assignee, never a done one", () => {
    expect(cardView(makeTask({ assignee: null }), NOW).unassigned).toBe(true);
    expect(cardView(makeTask({ assignee: null, status: "done" }), NOW).unassigned).toBe(false);
    expect(cardView(makeTask({ assignee: "lm" }), NOW).unassigned).toBe(false);
  });
});

describe("entranceDelay", () => {
  it("staggers the cards of a column and stops growing after the fifteenth", () => {
    expect(entranceDelay(0)).toBe("0ms");
    expect(entranceDelay(2)).toBe(`${2 * ENTRANCE_STEP_MS}ms`);
    expect(entranceDelay(40)).toBe(`${14 * ENTRANCE_STEP_MS}ms`);
  });
});
