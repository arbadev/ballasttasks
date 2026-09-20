"use client";

import { ArrowDown, ArrowUp, Check, Sparkles, X } from "lucide-react";
import { useId, useLayoutEffect, useRef, useSyncExternalStore } from "react";
import { cn } from "@/lib/cn";
import type { Task } from "../model/types";
import { useTaskCommands } from "../workspace/WorkspaceProvider";
import { ActionError, HIT_AREA, PanelButton, SECTION_LABEL } from "./controls";
import { useComposer, useDetailSession } from "./DetailSession";
import { StepTitle } from "./StepTitle";
import { StepGenerationPanel } from "./StepGenerationPanel";
import type { StepGenerationView } from "./useStepGeneration";

type Direction = "up" | "down";

const moveKey = (stepId: string, label: Direction) => `${stepId}:${label}`;

/** The checklist, its progress, the add box and, under it, the assistant's draft. */
export function StepsSection({ task, generation }: { task: Task; generation: StepGenerationView }) {
  const headingId = useId();
  const commands = useTaskCommands();
  const { track, stepOrders } = useDetailSession();
  const order = useSyncExternalStore(stepOrders.subscribe, () => stepOrders.get(task.id), () => "idle");
  const moveControls = useRef(new Map<string, HTMLButtonElement | null>());
  const reloadControl = useRef<HTMLButtonElement>(null);
  const lastMoved = useRef<{ taskId: string; stepId: string; label: Direction } | null>(null);
  const handBack = useRef(false);
  const move = (index: number, offset: number, label: Direction) => {
    const ids = task.steps.map((step) => step.id);
    [ids[index], ids[index + offset]] = [ids[index + offset], ids[index]];
    lastMoved.current = { taskId: task.id, stepId: ids[index + offset], label };
    handBack.current = true;
    stepOrders.run(task.id, () => track(task.id, commands.reorderSteps(task.id, ids)));
  };
  /** A move disables its own button and moves its row, which drops the focus; put it back. */
  useLayoutEffect(() => {
    if (order === "pending" || !handBack.current) return;
    handBack.current = false;
    const moved = lastMoved.current;
    if (!moved || moved.taskId !== task.id || document.activeElement !== document.body) return;
    const controls = order === "failed"
      ? [reloadControl.current]
      : [moveControls.current.get(moveKey(moved.stepId, moved.label)), moveControls.current.get(moveKey(moved.stepId, moved.label === "up" ? "down" : "up"))];
    controls.find((control) => !!control && !control.disabled)?.focus();
  }, [order, task.id]);
  const box = useComposer(`step:${task.id}`, (text) => track(task.id, commands.addStep(task.id, text)));

  const total = task.steps.length;
  const done = task.steps.filter((s) => s.done).length;
  const percent = total ? Math.round((done / total) * 100) : 0;
  const current = generation.generation;
  const running = current?.phase === "running" || (current?.phase === "proposed" && current.accepting) || (current?.phase === "error" && current.recovery === "reload");

  const save = (change: Promise<unknown>) => void track(task.id, change).catch(() => {});

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
        <ul aria-label="Steps" className="m-0 flex list-none flex-col gap-2 p-0">
          {task.steps.map((step, i) => (
            <li
              key={step.id}
              className="group/step flex animate-[bt-in_.3s_var(--ease)_both] flex-wrap items-start gap-2.5 border-b border-line py-2"
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
              <StepTitle taskId={task.id} step={step} />
              <div className="flex flex-none opacity-0 group-hover/step:opacity-100 group-focus-within/step:opacity-100 group-has-[[data-renaming]]/step:invisible pointer-coarse:order-1 pointer-coarse:w-full pointer-coarse:opacity-100">
                {([{ offset: -1, label: "up", Icon: ArrowUp }, { offset: 1, label: "down", Icon: ArrowDown }] as const).map(({ offset, label, Icon }) => <button
                  key={label} type="button" aria-label={`Move step ${label}: ${step.text}`}
                  ref={(control) => {
                    const controls = moveControls.current;
                    controls.set(moveKey(step.id, label), control);
                    return () => { controls.delete(moveKey(step.id, label)); };
                  }}
                  disabled={order !== "idle" || (offset === -1 ? i === 0 : i === total - 1)}
                  onClick={() => move(i, offset, label)}
                  className="grid h-5 w-6 cursor-pointer place-items-center rounded-bt-sm border-0 bg-transparent p-0 text-fg-3 transition-[color,background-color] duration-[160ms] ease-bt hover:bg-card hover:text-fg disabled:cursor-default disabled:opacity-40 pointer-coarse:h-11 pointer-coarse:w-11"
                ><Icon aria-hidden="true" size={14} /></button>)}
              </div>
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

      {order === "pending" && <p role="status" className="m-0 text-[12px] text-fg-3">Updating steps…</p>}
      {order === "failed" && <div role="alert" className="flex flex-wrap items-center gap-2 text-[12px] text-danger">
        <span>The last step move was not confirmed. Reload steps before moving again.</span>
        <PanelButton ref={reloadControl} variant="secondary" className="px-2 py-1" onClick={() => { handBack.current = true; stepOrders.run(task.id, () => commands.refreshTask(task.id), true); }}>Reload steps</PanelButton>
      </div>}

      <div className="flex items-center gap-2.5 py-1.5">
        <span aria-hidden="true" className="size-4 flex-none rounded-bt-sm border-[1.5px] border-dashed border-line-2" />
        <input
          aria-label="Add a step"
          name="new-step"
          placeholder="Add a step and press Enter"
          value={box.text}
          aria-busy={box.busy}
          onChange={(e) => box.setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") box.submit();
          }}
          className="min-w-0 flex-1 border-0 bg-transparent py-1 text-[13.5px] text-fg placeholder:text-fg-3 placeholder:opacity-100"
        />
      </div>
      {box.sending && (
        <p role="status" className="m-0 text-[12px] text-fg-3">
          Adding step… the box takes the next one when this lands.
        </p>
      )}
      {box.failed !== null && (
        <ActionError onRetry={box.retry} onDismiss={box.dismiss}>
          Could not add the step. It is kept, and Enter adds nothing until you retry or dismiss it.
        </ActionError>
      )}

      <StepGenerationPanel generation={generation} attachmentCount={task.attachments.length} />
    </section>
  );
}
