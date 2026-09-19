import { describe, expect, it } from "vitest";
import { NOW, due } from "@/test/tasks";
import { dayFrom, dueInfo, formatDueDate, toDueDate } from "./due";

describe("dueInfo", () => {
  it("reports a task without a date", () => {
    expect(dueInfo(null, NOW)).toEqual({
      label: "No date",
      overdue: false,
      isToday: false,
      inWeek: false,
      diff: Infinity,
    });
  });

  it("labels an overdue date with the number of days late", () => {
    expect(dueInfo(due(-2), NOW)).toEqual({
      label: "Overdue · 2d",
      overdue: true,
      isToday: false,
      inWeek: false,
      diff: -2,
    });
  });

  it("labels today, inside the week window", () => {
    expect(dueInfo(due(0), NOW)).toMatchObject({ label: "Due today", isToday: true, inWeek: true, diff: 0 });
  });

  it("labels tomorrow", () => {
    expect(dueInfo(due(1), NOW)).toMatchObject({ label: "Due tomorrow", isToday: false, inWeek: true, diff: 1 });
  });

  it("labels the rest of the week with weekday and distance", () => {
    expect(dueInfo(due(4), NOW)).toMatchObject({ label: "Due Tue · 4d", inWeek: true, diff: 4 });
    expect(dueInfo(due(6), NOW)).toMatchObject({ label: "Due Thu · 6d", inWeek: true, diff: 6 });
  });

  it("labels anything a week or more away with the short date, outside the week window", () => {
    expect(dueInfo(due(7), NOW)).toMatchObject({ label: "Due Sep 25", inWeek: false, diff: 7 });
    expect(dueInfo(due(13), NOW)).toMatchObject({ label: "Due Oct 1", inWeek: false, diff: 13 });
  });

  it("counts calendar days, whatever the time of day", () => {
    const justAfterMidnight = new Date(2026, 8, 18, 0, 5).getTime();
    const justBeforeMidnight = new Date(2026, 8, 18, 23, 55).getTime();
    expect(dueInfo(due(1), justAfterMidnight).diff).toBe(1);
    expect(dueInfo(due(1), justBeforeMidnight).diff).toBe(1);
    expect(dueInfo(due(0), justBeforeMidnight).isToday).toBe(true);
  });

  it("stays a whole number of days across a daylight-saving change", () => {
    const beforeChange = new Date(2026, 9, 23, 10, 0).getTime();
    expect(dueInfo("2026-11-03", beforeChange).diff).toBe(11);
  });
});

describe("due date helpers", () => {
  it("formats a due date as the design's short date", () => {
    expect(formatDueDate("2026-09-25")).toBe("Sep 25");
  });

  it("converts a Date to the local calendar day", () => {
    expect(toDueDate(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
  });

  it("offsets from today by default", () => {
    expect(dayFrom(1, NOW)).toBe("2026-09-19");
    expect(dayFrom(-6, NOW)).toBe("2026-09-12");
  });

  it("offsets from a base date when one is given", () => {
    expect(dayFrom(7, NOW, "2026-09-28")).toBe("2026-10-05");
  });
});
