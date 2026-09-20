import type { DueDate } from "./types";

const DAY_MS = 864e5;

export interface DueInfo {
  label: string;
  overdue: boolean;
  isToday: boolean;
  /** Due today or within the next six days. */
  inWeek: boolean;
  /** Whole calendar days from today; negative when late, Infinity without a date. */
  diff: number;
}

/** A task date is a UTC calendar day, never a browser-local instant. */
function parse(due: DueDate): Date {
  return new Date(`${due}T00:00:00Z`);
}

export function toDueDate(date: Date): DueDate {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

/** The day `offset` days after `base` (the injected instant's UTC day when omitted). */
export function dayFrom(offset: number, now: number, base?: DueDate): DueDate {
  const d = base ? parse(base) : new Date(now);
  d.setUTCDate(d.getUTCDate() + offset);
  return toDueDate(d);
}

/** "Sep 25" */
export function formatDueDate(due: DueDate): string {
  return parse(due).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

export function dueInfo(due: DueDate | null, now: number): DueInfo {
  if (!due) return { label: "No date", overdue: false, isToday: false, inWeek: false, diff: Infinity };
  const date = parse(due);
  const diff = Math.floor(date.getTime() / DAY_MS) - Math.floor(now / DAY_MS);
  if (diff < 0) return { label: `Overdue · ${-diff}d`, overdue: true, isToday: false, inWeek: false, diff };
  if (diff === 0) return { label: "Due today", overdue: false, isToday: true, inWeek: true, diff };
  if (diff === 1) return { label: "Due tomorrow", overdue: false, isToday: false, inWeek: true, diff };
  if (diff < 7) {
    const weekday = date.toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" });
    return { label: `Due ${weekday} · ${diff}d`, overdue: false, isToday: false, inWeek: true, diff };
  }
  return { label: `Due ${formatDueDate(due)}`, overdue: false, isToday: false, inWeek: false, diff };
}
