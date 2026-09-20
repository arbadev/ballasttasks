import type { Step } from "./types";

/** Same title rule as domain/step.py; the server remains authoritative. */
export function validStepTitle(text: string): boolean {
  const title = text.trim();
  return title.length > 0 && [...title].length <= 200 && !title.includes("\0");
}

export function renameStep(steps: Step[], stepId: string, text: string): Step[] {
  if (!validStepTitle(text)) throw new Error("Use a step title of 1–200 characters without NUL.");
  const step = steps.find((s) => s.id === stepId);
  if (!step) throw new Error("This step no longer exists. Reload the task.");
  const title = text.trim();
  return title === step.text ? steps : steps.map((s) => s.id === stepId ? { ...s, text: title } : s);
}

/** Array order is the UI's dense position; never filter missing or foreign IDs. */
export function reorderSteps(steps: Step[], ids: string[]): Step[] {
  const byId = new Map(steps.map((s) => [s.id, s]));
  if (ids.length > 100 || ids.length !== steps.length || new Set(ids).size !== ids.length || ids.some((id) => !byId.has(id))) {
    throw new Error("Step order must include every current step exactly once. Reload steps.");
  }
  return ids.every((id, index) => id === steps[index].id) ? steps : ids.map((id) => byId.get(id)!);
}
