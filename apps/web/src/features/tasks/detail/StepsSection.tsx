"use client";

import { Check, Sparkles, X } from "lucide-react";
import { useId } from "react";
import { cn } from "@/lib/cn";
import type { Task } from "../model/types";
import { useTaskCommands } from "../workspace/WorkspaceProvider";
import { HIT_AREA, PanelButton, SECTION_LABEL } from "./controls";
import { useDetailSession, useDraft } from "./DetailSession";
import { StepGenerationPanel } from "./StepGenerationPanel";
import type { StepGenerationView } from "./useStepGeneration";

/** The checklist, its progress, the add box and, under it, the assistant's draft. */
export function StepsSection({ task, generation }: { task: Task; generation: StepGenerationView }) {
  const headingId = useId();
  const commands = useTaskCommands();
  const { track } = useDetailSession();
  const [newStep, setNewStep] = useDraft(`step:${task.id}`);

  const total = task.steps.length;
  const done = task.steps.filter((s) => s.done).length;
  const percent = total ? Math.round((done / total) * 100) : 0;
  const running = generation.generation?.phase === "running";

  const save = (change: Promise<unknown>) => void track(change).catch(() => {});

  const addStep = () => {
    const text = newStep.trim();
    if (!text) return;
    setNewStep("");
    void track(commands.addStep(task.id, text)).catch(() => setNewStep(text));
  };

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2 border-t border-line pt-[18px]">
      <div className="flex flex-wrap items-center gap-3">
        <h3 id={headingId} className={SECTION_LABEL}>
          Steps
        </h3>
        <span className="font-mono text-[12px] text-fg-2">{total ? `${done}/${total}` : "none yet"}</span>
        <span
          role="progressbar"
          aria-label="Steps completed"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          className="h-[3px] max-w-[160px] flex-1 overflow-hidden rounded-[2px] bg-line-2"
        >
          <span className="block h-full rounded-[2px] bg-acc transition-[width] duration-500 ease-bt" style={{ width: `${percent}%` }} />
        </span>
        <PanelButton variant="accent" icon={Sparkles} iconSize={14} disabled={running} onClick={generation.start} className="ml-auto">
          Generate steps
        </PanelButton>
      </div>

      {total > 0 && (
        <ul aria-label="Steps" className="m-0 flex list-none flex-col p-0">
          {task.steps.map((step, i) => (
            <li
              key={step.id}
              className="flex animate-[bt-in_.3s_var(--ease)_both] items-start gap-2.5 border-b border-line py-2"
              style={{ animationDelay: `${Math.min(i, 10) * 30}ms` }}
            >
              <button
                type="button"
                role="checkbox"
                aria-checked={step.done}
                aria-label={step.text}
                onClick={() => save(commands.toggleStep(task.id, step.id))}
                className={cn(
                  "mt-[3px] grid size-4 flex-none cursor-pointer place-items-center rounded-bt-sm border-[1.5px] p-0 text-acc-fg transition-[border-color,background-color,transform] duration-[160ms] ease-bt hover:scale-110 hover:border-acc",
                  HIT_AREA,
                  step.done ? "border-acc bg-acc" : "border-line-2 bg-transparent",
                )}
              >
                {step.done && <Check aria-hidden="true" size={11} strokeWidth={3} className="animate-bt-pop" />}
              </button>
              <span className={cn("min-w-0 flex-1 text-[13.5px] break-words transition-colors duration-200 ease-bt", step.done ? "text-fg-3 line-through" : "text-fg")}>
                {step.text}
              </span>
              <button
                type="button"
                aria-label={`Remove step: ${step.text}`}
                onClick={() => save(commands.removeStep(task.id, step.id))}
                className={cn(
                  "grid flex-none cursor-pointer place-items-center border-0 bg-transparent p-0.5 text-fg-3 opacity-60 transition-[opacity,color] duration-[160ms] ease-bt hover:text-danger hover:opacity-100 focus-visible:opacity-100",
                  HIT_AREA,
                )}
              >
                <X aria-hidden="true" size={14} strokeWidth={2} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-center gap-2.5 py-1.5">
        <span aria-hidden="true" className="size-4 flex-none rounded-bt-sm border-[1.5px] border-dashed border-line-2" />
        <input
          aria-label="Add a step"
          placeholder="Add a step and press Enter"
          value={newStep}
          onChange={(e) => setNewStep(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") addStep();
          }}
          className="min-w-0 flex-1 border-0 bg-transparent py-1 text-[13.5px] text-fg placeholder:text-fg-3 placeholder:opacity-100"
        />
      </div>

      <StepGenerationPanel generation={generation} attachmentCount={task.attachments.length} />
    </section>
  );
}
