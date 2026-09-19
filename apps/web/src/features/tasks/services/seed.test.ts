import { describe, expect, it } from "vitest";
import { NOW, due } from "@/test/tasks";
import { SEED_PEOPLE, SEED_PROJECTS, seedTasks } from "./seed";

describe("seed data", () => {
  const tasks = seedTasks(NOW);

  it("is the design's sixteen tasks, thirteen of them open", () => {
    expect(tasks.map((t) => t.id)).toEqual(Array.from({ length: 16 }, (_, i) => `t${i + 1}`));
    expect(tasks.filter((t) => t.status !== "done")).toHaveLength(13);
  });

  it("has the design's four people and two projects", () => {
    expect(SEED_PEOPLE.map((p) => [p.id, p.name, p.initials, p.role])).toEqual([
      ["ab", "Andres Barradas", "AB", "owner"],
      ["lm", "Lucía Marín", "LM", "backend"],
      ["tr", "Tomás Rey", "TR", "frontend"],
      ["ai", "Assistant", "AI", "system"],
    ]);
    expect(SEED_PROJECTS).toEqual([
      { id: "ballast", name: "Ballast Tasks", tone: "accent" },
      { id: "inbox", name: "Inbox", tone: "muted" },
    ]);
  });

  it("dates everything relative to the clock it is given", () => {
    const t1 = tasks[0];
    expect(t1).toMatchObject({
      title: "Task CRUD endpoints with pagination and filters",
      status: "progress",
      project: "ballast",
      assignee: "ab",
      due: due(3),
      prio: 0,
      importance: 95,
      createdAt: NOW - 4 * 864e5,
      updatedAt: NOW - 0.8 * 864e5,
    });
    expect(t1.steps).toHaveLength(6);
    expect(t1.steps.filter((s) => s.done)).toHaveLength(3);
    expect(t1.attachments.map((a) => a.kind)).toEqual(["pdf", "link"]);
    expect(t1.activity).toHaveLength(5);
    expect(t1.activity[2]).toMatchObject({ type: "comment", who: "lm", at: NOW - 864e5 - 3 * 36e5 });
  });

  it("applies the design's defaults: unassigned, undated, created 3 days ago, updated yesterday", () => {
    const t7 = tasks.find((t) => t.id === "t7")!;
    expect(t7).toMatchObject({ assignee: null, due: null, steps: [], attachments: [], createdAt: NOW - 3 * 864e5 });
    const t15 = tasks.find((t) => t.id === "t15")!;
    expect(t15).toMatchObject({ description: "", project: "inbox", due: null, updatedAt: NOW - 864e5 });
  });

  it("gives every step a unique id", () => {
    const ids = tasks.flatMap((t) => t.steps.map((s) => s.id));
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toHaveLength(30);
  });
});
