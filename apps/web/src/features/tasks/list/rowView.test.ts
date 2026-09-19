import { describe, expect, it } from "vitest";
import { NOW, due, makeTask } from "@/test/tasks";
import { rowView } from "./rowView";

const view = (overrides: Parameters<typeof makeTask>[0], index = 0) => rowView(makeTask(overrides), NOW, index);

describe("rowView: the due label and its tone", () => {
  it("an overdue open task is danger, with the alert icon and a danger rail", () => {
    expect(view({ due: due(-2) })).toMatchObject({ dueLabel: "Overdue · 2d", dueTone: "danger", dueIcon: "overdue", rail: "danger" });
  });

  it("a task due today is warn, with the clock icon and a warn rail", () => {
    expect(view({ due: due(0) })).toMatchObject({ dueLabel: "Due today", dueTone: "warn", dueIcon: "soon", rail: "warn" });
  });

  it("a task due inside the soon window is warn", () => {
    expect(view({ due: due(1) })).toMatchObject({ dueLabel: "Due tomorrow", dueTone: "warn", dueIcon: "soon", rail: "warn" });
  });

  it("a task due later is quiet, with the calendar icon and no rail", () => {
    expect(view({ due: due(9) })).toMatchObject({ dueTone: "later", dueIcon: "later", rail: "none" });
  });

  it("an undated task reads No date", () => {
    expect(view({ due: null })).toMatchObject({ dueLabel: "No date", dueTone: "later", dueIcon: "later", rail: "none" });
  });

  it("a done task shows the bare date and no urgency, however late it was", () => {
    expect(view({ due: "2026-09-10", status: "done" })).toMatchObject({ dueLabel: "Sep 10", dueTone: "later", dueIcon: "later", rail: "none", done: true });
  });

  it("a done task without a date still reads No date", () => {
    expect(view({ due: null, status: "done" }).dueLabel).toBe("No date");
  });
});

describe("rowView: priority", () => {
  it("maps P0 to P3 onto the danger, accent and two neutral tones", () => {
    expect([0, 1, 2, 3].map((prio) => view({ prio: prio as 0 | 1 | 2 | 3 }).prioTone)).toEqual(["danger", "accent", "neutral", "muted"]);
    expect(view({ prio: 1 }).prioLabel).toBe("P1");
  });

  it("a P0 at risk is hot, gets a danger rail and blinks", () => {
    expect(view({ prio: 0, due: due(3) })).toMatchObject({ prioTone: "hot", rail: "danger", blink: true, dueTone: "warn" });
  });

  it("an overdue P0 is hot; an overdue P1 is not", () => {
    expect(view({ prio: 0, due: due(-1) })).toMatchObject({ prioTone: "hot", blink: true });
    expect(view({ prio: 1, due: due(-1) })).toMatchObject({ prioTone: "accent", blink: false });
  });
});

describe("rowView: marks", () => {
  it("importance of 85 or more is accented", () => {
    expect(view({ importance: 85 })).toMatchObject({ importance: 85, importanceAccent: true });
    expect(view({ importance: 84 }).importanceAccent).toBe(false);
  });

  it("counts done steps and attachments, and omits them when there are none", () => {
    const steps = [
      { id: "a", text: "a", done: true },
      { id: "b", text: "b", done: false },
      { id: "c", text: "c", done: true },
    ];
    const attachments = [{ kind: "pdf" as const, name: "x.pdf", meta: "1 MB" }];
    expect(view({ steps, attachments })).toMatchObject({ stepsLabel: "2/3", attachmentCount: 1 });
    expect(view({})).toMatchObject({ stepsLabel: null, attachmentCount: 0 });
  });

  it("an open task without an assignee needs an owner; a done one does not", () => {
    expect(view({ assignee: null }).needsOwner).toBe(true);
    expect(view({ assignee: null, status: "done" }).needsOwner).toBe(false);
    expect(view({ assignee: "ab" }).needsOwner).toBe(false);
  });
});

describe("rowView: entrance stagger", () => {
  it("delays each row by 24ms, capped at the fifteenth", () => {
    expect([0, 1, 14, 15, 40].map((i) => view({}, i).delayMs)).toEqual([0, 24, 336, 336, 336]);
  });
});
