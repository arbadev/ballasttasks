import { describe, expect, it } from "vitest";
import { NOW } from "@/test/tasks";
import { sidebarCounts } from "../model/counts";
import { DEFAULT_QUERY, DEFAULT_SORT, selectTasks } from "../model/filter";
import { attentionSignals } from "../model/signals";
import { CURRENT_USER_ID, seedTasks } from "./seed";

// The numbers the design itself renders on first load: the seed and the model together
// must reproduce them, which is what ties this port to the reference.
describe("seed + model reproduce the design's first screen", () => {
  const tasks = seedTasks(NOW);
  const context = { now: NOW, currentUserId: CURRENT_USER_ID };

  it("sidebar: 13 open, 7 mine, 1 overdue; Ballast Tasks 11, Inbox 2", () => {
    expect(sidebarCounts(tasks, context)).toEqual({ all: 13, mine: 7, overdue: 1, byProject: { ballast: 11, inbox: 2 } });
  });

  it("Attention: 1 overdue, 2 P0 at risk, 4 due soon, 2 need an owner", () => {
    const signals = attentionSignals(tasks, { now: NOW, project: "all", active: null });
    expect(signals.map((s) => `${s.count} ${s.label}`)).toEqual(["1 overdue", "2 P0 at risk", "4 due soon", "2 need an owner"]);
  });

  it("list: 13 tasks in the design's urgency order", () => {
    const titles = selectTasks(tasks, DEFAULT_QUERY, DEFAULT_SORT, context).map((t) => t.title);
    expect(titles).toHaveLength(13);
    expect(titles.slice(0, 8)).toEqual([
      "Write PRD.md: overview, user stories, scope",
      "JWT authentication",
      "Task CRUD endpoints with pagination and filters",
      "Confirm the panel slot with the recruiter",
      "Docker compose: five services from .env.example",
      "Unit tests at 80% coverage or more",
      "Generate-steps job: Celery worker + LanguageModel port",
      "Next.js task list and board",
    ]);
  });
});
