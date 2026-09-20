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

  it("counts UTC calendar days, whatever the time of day", () => {
    const justAfterMidnight = Date.parse("2026-09-18T00:05:00Z");
    const justBeforeMidnight = Date.parse("2026-09-18T23:55:00Z");
    expect(dueInfo(due(1), justAfterMidnight).diff).toBe(1);
    expect(dueInfo(due(1), justBeforeMidnight).diff).toBe(1);
    expect(dueInfo(due(0), justBeforeMidnight).isToday).toBe(true);
  });

  it("stays a whole number of days across a daylight-saving change", () => {
    const beforeChange = Date.parse("2026-10-23T10:00:00Z");
    expect(dueInfo("2026-11-03", beforeChange).diff).toBe(11);
  });
});

describe("UTC task calendar boundaries", () => {
  it.each(["2026-09-19T19:56:08-05:00", "2026-09-20T14:56:08+14:00"])("matches the API's four-day distance at %s", (instant) => {
    const now = Date.parse(instant);
    expect(dueInfo("2026-09-24", now)).toMatchObject({ label: "Due Thu · 4d", diff: 4 });
    expect(dayFrom(0, now)).toBe("2026-09-20");
    expect(dayFrom(1, now)).toBe("2026-09-21");
  });

  it("changes Today precisely at UTC midnight", () => {
    const before = Date.parse("2026-09-19T23:59:59.999Z");
    const after = before + 1;
    expect(dueInfo("2026-09-20", before)).toMatchObject({ label: "Due tomorrow", diff: 1, isToday: false });
    expect(dueInfo("2026-09-20", after)).toMatchObject({ label: "Due today", diff: 0, isToday: true });
    expect(dueInfo("2026-09-19", after)).toMatchObject({ label: "Overdue · 1d", diff: -1, overdue: true });
    expect(dayFrom(1, before)).toBe("2026-09-20");
    expect(dayFrom(1, after)).toBe("2026-09-21");
  });

  it.each([
    ["2026-03-08T01:59:59-05:00", "2026-03-09"],
    ["2026-03-08T03:00:00-04:00", "2026-03-09"],
    ["2026-11-01T01:30:00-04:00", "2026-11-02"],
    ["2026-11-01T01:30:00-05:00", "2026-11-02"],
    ["2026-03-29T01:30:00+01:00", "2026-03-30"],
    ["2026-03-29T03:30:00+02:00", "2026-03-30"],
  ])("keeps UTC dates stable across DST at %s", (instant, tomorrow) => {
    const now = Date.parse(instant);
    expect(dayFrom(1, now)).toBe(tomorrow);
    expect(dueInfo(tomorrow, now)).toMatchObject({ label: "Due tomorrow", diff: 1 });
  });

  it.each(["2026-03-08", "2026-11-01", "2028-02-29"])("does not shift an entered date-only value %s", (entered) => {
    expect(dayFrom(0, Date.parse("2026-09-20T00:00:00Z"), entered)).toBe(entered);
  });
});

describe("due date helpers", () => {
  it("formats a due date as the design's short date", () => {
    expect(formatDueDate("2026-09-25")).toBe("Sep 25");
  });

  it("converts an instant to its UTC calendar day, not its offset's local date", () => {
    expect(toDueDate(new Date("2026-01-05T23:59:00-05:00"))).toBe("2026-01-06");
    expect(toDueDate(new Date("2026-01-05T00:01:00+14:00"))).toBe("2026-01-04");
  });

  it("offsets from today by default", () => {
    expect(dayFrom(1, NOW)).toBe("2026-09-19");
    expect(dayFrom(-6, NOW)).toBe("2026-09-12");
  });

  it("offsets from a base date when one is given", () => {
    expect(dayFrom(7, NOW, "2026-09-28")).toBe("2026-10-05");
  });
});
