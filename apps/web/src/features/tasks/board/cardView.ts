import type { Task } from "../model/types";

export type CardTone = "danger" | "warn";

export interface CardView {
  done: boolean;
  dueLabel: string;
  dueTone: CardTone | null;
  dueMark: "overdue" | "soon" | "later";
  rail: CardTone | null;
  blink: boolean;
  prioLabel: string;
  prioTone: "hot" | "p0" | "p1" | "p2" | "p3";
  stepsLabel: string | null;
  attachmentsLabel: string | null;
  unassigned: boolean;
}

export const ENTRANCE_STEP_MS = 24;

export function cardView(task: Task, now: number): CardView {
  throw new Error(`cardView is not implemented (${task.id}, ${now}).`);
}

export function entranceDelay(index: number): string {
  throw new Error(`entranceDelay is not implemented (${index}).`);
}
