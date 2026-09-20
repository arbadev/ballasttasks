"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import type { Step } from "../model/types";
import { validStepTitle } from "../model/stepEditing";
import { useTaskCommands } from "../workspace/WorkspaceProvider";
import { ActionError, BOX_INPUT, PanelButton } from "./controls";
import { useComposer, useDetailSession } from "./DetailSession";

/** An explicit inline edit; its held send and next draft use the existing session owner. */
export function StepTitle({ taskId, step }: { taskId: string; step: Step }) {
  const commands = useTaskCommands();
  const { track } = useDetailSession();
  const box = useComposer(`rename-step:${taskId}:${step.id}`, (text) => track(taskId, commands.renameStep(taskId, step.id, text)));
  const [opened, setOpened] = useState(false);
  const [submitted, setSubmitted] = useState<string | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const previous = useRef(false);
  const editing = opened || box.text !== "" || box.busy;
  const shown = submitted !== null && box.sending ? submitted : box.text;
  useLayoutEffect(() => {
    if (previous.current && !editing && document.activeElement === document.body) button.current?.focus();
    previous.current = editing;
  }, [editing]);
  const type = (next: string) => {
    setSubmitted(null);
    box.setText(next);
  };
  const submit = () => {
    if (!validStepTitle(box.text) || box.busy) return;
    setOpened(false);
    setSubmitted(box.text);
    box.submit();
  };
  const cancel = () => {
    if (box.sending) return;
    box.dismiss();
    type("");
    setOpened(false);
  };
  return <div className="min-w-0 flex-1">
    {editing ? <div data-renaming="" className="flex flex-col gap-2" onKeyDown={(e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); }
    }}>
      <input autoFocus aria-label="Step title" name={`step-title-${step.id}`} value={shown}
        aria-busy={box.sending} aria-invalid={!validStepTitle(shown)}
        onChange={(e) => type(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }}
        className={cn(BOX_INPUT, "min-w-0 px-2 py-1 text-[13.5px]")} />
      <div className="flex flex-wrap gap-2">
        <PanelButton variant="secondary" className="px-2 py-1" aria-label="Save step title" disabled={box.busy || !validStepTitle(shown)} onClick={submit}>Save</PanelButton>
        <PanelButton variant="quiet" aria-label="Cancel step rename" disabled={box.sending} onClick={cancel}>Cancel</PanelButton>
      </div>
      {box.sending && <p role="status" className="m-0 text-[12px] text-fg-3">Saving step title…</p>}
      {box.failed !== null && <ActionError onRetry={box.retry} onDismiss={box.dismiss}>Could not rename the step. Your text is kept.</ActionError>}
    </div> : <button ref={button} type="button" aria-label={`Rename step: ${step.text}`}
      onClick={() => { type(step.text); setOpened(true); }}
      className={cn("block w-full cursor-text border-0 bg-transparent p-0 text-left text-[13.5px] break-words transition-[color] duration-200 ease-bt", step.done ? "text-fg-3 line-through" : "text-fg")}>
      {step.text}
    </button>}
  </div>;
}
