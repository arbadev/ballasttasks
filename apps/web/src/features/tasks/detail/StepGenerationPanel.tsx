"use client";

import { Sparkles, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { HIT_AREA, PanelButton } from "./controls";
import type { StepGenerationView } from "./useStepGeneration";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

const SHIMMER = "block h-2.5 animate-bt-shimmer rounded-[4px] bg-linear-90/srgb from-card-2 from-25% via-line-2 via-50% to-card-2 to-75% bg-[length:200%_100%]";

/** The inline AI surface under the checklist: drafting, the proposal, or a failed start. */
export function StepGenerationPanel({ generation: view, attachmentCount }: { generation: StepGenerationView; attachmentCount: number }) {
  const { generation, failed } = view;

  if (failed && !generation) {
    return (
      <div role="alert" className="flex animate-[bt-in_.25s_var(--ease)] flex-wrap items-center gap-x-3 gap-y-2 rounded-bt border border-danger/35 bg-danger-soft px-3.5 py-3 text-[13px] text-fg">
        <span className="flex-1">Could not draft steps. Nothing was changed.</span>
        <PanelButton variant="secondary" className="h-[30px] px-2.5" onClick={view.start}>
          Retry
        </PanelButton>
      </div>
    );
  }

  if (generation?.phase === "running") {
    return (
      <div role="status" aria-label="Drafting steps" className="flex animate-[bt-in_.25s_var(--ease)] flex-col gap-3 rounded-bt border border-line bg-card p-3.5">
        <div className="flex flex-wrap items-center gap-2 text-[13px]">
          <Sparkles aria-hidden="true" size={14} strokeWidth={2} className="animate-bt-pulse text-acc" />
          <span className="font-medium">Drafting steps</span>
          <span className="text-fg-3">reading the title, description and {plural(attachmentCount, "attachment")}</span>
        </div>
        <div aria-hidden="true" className="flex flex-col gap-[9px]">
          <span className={cn(SHIMMER, "w-[72%]")} />
          <span className={cn(SHIMMER, "w-[58%] [animation-delay:.12s]")} />
          <span className={cn(SHIMMER, "w-[66%] [animation-delay:.24s]")} />
        </div>
        <div className="font-mono text-[10.5px] text-fg-3">background job · keep editing, the draft lands here</div>
      </div>
    );
  }

  if (generation?.phase === "proposed") {
    const count = generation.steps.length;
    return (
      <div
        role="group"
        aria-label="Proposed steps"
        className="flex animate-[bt-in_.3s_var(--ease)] flex-col gap-1.5 rounded-bt border border-acc/40 bg-linear-to-b/srgb from-acc-soft to-transparent to-140% p-3.5"
      >
        <div className="flex items-center gap-2 text-[13px]">
          <Sparkles aria-hidden="true" size={14} strokeWidth={2} className="flex-none text-acc" />
          <span aria-live="polite" className="font-medium">
            Assistant drafted {plural(count, "step")}
          </span>
          <span className="ml-auto inline-flex h-5 items-center rounded-bt-sm bg-acc-soft px-[7px] font-mono text-[10.5px] tracking-[.04em] text-acc">proposed</span>
        </div>
        <p className="m-0 mb-1.5 text-[12.5px] text-fg-2">
          Drafted from the title, description and attachments. Remove what doesn&apos;t fit — nothing is added until you say so.
        </p>
        <ul aria-label="Proposed steps" className="m-0 flex list-none flex-col p-0">
          {generation.steps.map((step, i) => (
            <li
              key={step.id}
              className="flex animate-[bt-in_.3s_var(--ease)_both] items-start gap-2.5 border-t border-line py-[7px]"
              style={{ animationDelay: `${i * 60}ms` }}
            >
              <span aria-hidden="true" className="mt-[3px] size-4 flex-none rounded-bt-sm border-[1.5px] border-dashed border-acc opacity-70" />
              <span className="min-w-0 flex-1 text-[13.5px] break-words">{step.text}</span>
              <button
                type="button"
                aria-label={`Remove proposed step: ${step.text}`}
                onClick={() => view.removeProposed(step.id)}
                className={cn(
                  "grid flex-none cursor-pointer place-items-center border-0 bg-transparent p-0.5 text-fg-3 opacity-70 transition-[opacity,color] duration-[160ms] ease-bt hover:text-danger hover:opacity-100 focus-visible:opacity-100",
                  HIT_AREA,
                )}
              >
                <X aria-hidden="true" size={14} strokeWidth={2} />
              </button>
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap gap-2 pt-2.5">
          <PanelButton variant="accent" disabled={count === 0} onClick={view.accept}>
            Add {plural(count, "step")}
          </PanelButton>
          <PanelButton variant="secondary" className="h-8 px-3" onClick={view.start}>
            Regenerate
          </PanelButton>
          <PanelButton variant="quiet" className="h-8" onClick={view.discard}>
            Discard
          </PanelButton>
        </div>
      </div>
    );
  }

  return null;
}
