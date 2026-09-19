import type { ProjectFilter, SignalId } from "./filter";
import type { Task } from "./types";
import { urgency, type Urgency } from "./urgency";

export interface AttentionSignal {
  id: SignalId;
  label: string;
  count: number;
  tone: "danger" | "warn" | "info";
  /** The dot pulses for P0 at risk. */
  blink: boolean;
  active: boolean;
}

interface SignalDefinition {
  id: SignalId;
  one: string;
  many: string;
  tone: AttentionSignal["tone"];
  blink: boolean;
  matches: (u: Urgency) => boolean;
}

const DEFINITIONS: readonly SignalDefinition[] = [
  { id: "overdue", one: "overdue", many: "overdue", tone: "danger", blink: false, matches: (u) => u.overdue },
  { id: "critical", one: "P0 at risk", many: "P0 at risk", tone: "danger", blink: true, matches: (u) => u.critical },
  { id: "soon", one: "due soon", many: "due soon", tone: "warn", blink: false, matches: (u) => !u.overdue && (u.today || u.soon) },
  { id: "unassigned", one: "needs an owner", many: "need an owner", tone: "info", blink: false, matches: (u) => u.unassigned },
];

/**
 * The Attention strip: counts over the open tasks of the selected project. It deliberately
 * ignores scope and the toolbar filters, so it always describes the whole project. Empty
 * signals are hidden, except the active one, which must stay reachable to switch it off.
 */
export function attentionSignals(
  tasks: readonly Task[],
  context: { now: number; project: ProjectFilter; active: SignalId | null },
): AttentionSignal[] {
  const scoped = tasks
    .filter((t) => t.status !== "done" && (context.project === "all" || t.project === context.project))
    .map((t) => urgency(t, context.now));

  return DEFINITIONS.map((d) => {
    const count = scoped.filter(d.matches).length;
    return { id: d.id, label: count === 1 ? d.one : d.many, count, tone: d.tone, blink: d.blink, active: context.active === d.id };
  }).filter((s) => s.count > 0 || s.active);
}
