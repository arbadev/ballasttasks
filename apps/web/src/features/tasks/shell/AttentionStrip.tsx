"use client";

import { X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { attentionSignals, signalsFromCounts, type AttentionSignal } from "../model/signals";
import { useNow, useWorkspace } from "../workspace/WorkspaceProvider";

const TONES: Record<AttentionSignal["tone"], { dot: string; active: string; hover: string }> = {
  danger: { dot: "bg-danger", active: "border-danger bg-danger-soft text-danger", hover: "hover:border-danger" },
  warn: { dot: "bg-warn", active: "border-warn bg-warn-soft text-warn", hover: "hover:border-warn" },
  info: { dot: "bg-info", active: "border-info bg-info-soft text-info", hover: "hover:border-info" },
};

/** What needs attention in the selected project; each chip filters the view to its tasks. */
export function AttentionStrip() {
  const { state, actions } = useWorkspace();
  const now = useNow();
  const signals = state.page ? signalsFromCounts(state.page.signals, state.query.signal) : attentionSignals(state.tasks, { now, project: state.query.project, active: state.query.signal });

  return (
    <section aria-label="Attention" className="flex flex-wrap items-center gap-2 border-b border-line bg-panel px-6 py-[9px] max-md:px-4">
      <span aria-hidden="true" className="mr-1 font-mono text-[10.5px] tracking-[.1em] text-fg-3 uppercase">
        Attention
      </span>
      {signals.map((signal) => {
        const tone = TONES[signal.tone];
        return (
          <button
            key={signal.id}
            type="button"
            aria-pressed={signal.active}
            onClick={() => actions.toggleSignal(signal.id)}
            className={cn(
              "inline-flex h-7 cursor-pointer items-center gap-[7px] rounded-bt border pr-2.5 pl-[9px] text-[12.5px] font-medium transition-[background-color,border-color,color,transform] duration-[160ms] ease-bt hover:-translate-y-px pointer-coarse:min-h-11",
              tone.hover,
              signal.active ? tone.active : "border-line bg-card text-fg-2",
            )}
          >
            <span aria-hidden="true" className={cn("size-[7px] rounded-full", tone.dot, signal.blink && "animate-bt-blink")} />
            <span className="font-mono text-xs tabular-nums">{signal.count}</span>
            <span>{signal.label}</span>
          </button>
        );
      })}
      {state.load.status === "ready" && signals.length === 0 && (
        <span className="inline-flex items-center gap-[7px] text-[12.5px] text-ok">
          <span aria-hidden="true" className="size-[7px] rounded-full bg-ok" />
          All clear — nothing overdue, at risk or unowned
        </span>
      )}
      {state.query.signal && (
        <Button variant="ghost" icon={X} onClick={actions.clearSignal} className="ml-auto">
          Show all
        </Button>
      )}
    </section>
  );
}
