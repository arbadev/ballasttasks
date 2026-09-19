import { describe, expect, it } from "vitest";
import { NOW } from "@/test/tasks";
import { relativeTime } from "./time";

const MIN = 60_000;
const HOUR = 60 * MIN;

describe("relativeTime", () => {
  it.each([
    [0, "just now"],
    [29_000, "just now"],
    [MIN, "1 min ago"],
    [59 * MIN, "59 min ago"],
    [60 * MIN, "1 h ago"],
    [23 * HOUR, "23 h ago"],
    [24 * HOUR, "yesterday"],
    [36 * HOUR, "2 days ago"],
    [6 * 24 * HOUR, "6 days ago"],
  ])("describes %i ms ago as %s", (elapsed, expected) => {
    expect(relativeTime(NOW - elapsed, NOW)).toBe(expected);
  });
});
