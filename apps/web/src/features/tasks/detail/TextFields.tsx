"use client";

import { useId, type Ref } from "react";
import type { Task } from "../model/types";
import { useTaskCommands } from "../workspace/WorkspaceProvider";
import { FieldLabel, SaveError } from "./controls";
import { useDetailSession } from "./DetailSession";
import { AUTOSAVE_DELAY_MS, useAutosaveField } from "./useAutosaveField";

/** The task name, set as the panel's headline. Saves itself shortly after typing stops. */
export function TitleField({ task, inputRef }: { task: Task; inputRef: Ref<HTMLInputElement> }) {
  const commands = useTaskCommands();
  const { track } = useDetailSession();
  const field = useAutosaveField({
    saved: task.title,
    save: (title: string) => track(commands.update(task.id, { title })),
    delay: AUTOSAVE_DELAY_MS,
  });

  return (
    <div className="flex flex-col gap-1.5">
      <input
        ref={inputRef}
        aria-label="Task name"
        name="title"
        placeholder="Task name"
        value={field.value}
        onChange={(e) => field.change(e.target.value)}
        onBlur={field.flush}
        className="w-full border-0 border-b border-transparent bg-transparent pt-0.5 pb-2 font-heading text-[length:calc(var(--hsize)+2px)] leading-[1.2] font-[var(--hw)] tracking-[var(--hls)] text-fg transition-colors duration-[160ms] ease-bt placeholder:text-fg-3 placeholder:opacity-100 focus:border-b-acc"
      />
      {field.failed && <SaveError what="title" onRetry={field.retry} />}
    </div>
  );
}

export function DescriptionField({ task }: { task: Task }) {
  const id = useId();
  const commands = useTaskCommands();
  const { track } = useDetailSession();
  const field = useAutosaveField({
    saved: task.description,
    save: (description: string) => track(commands.update(task.id, { description })),
    delay: AUTOSAVE_DELAY_MS,
  });

  return (
    <div className="flex flex-col gap-1.5">
      <FieldLabel htmlFor={id}>Description</FieldLabel>
      <textarea
        id={id}
        name="description"
        rows={4}
        placeholder="What does done look like?"
        value={field.value}
        onChange={(e) => field.change(e.target.value)}
        onBlur={field.flush}
        className="block min-h-[88px] w-full resize-y rounded-bt border border-line bg-card px-3 py-2.5 text-[13.5px] leading-[1.55] text-fg transition-[border-color,box-shadow] duration-[160ms] ease-bt placeholder:text-fg-3 placeholder:opacity-100 focus:border-acc focus:shadow-[0_0_0_3px_var(--acc-soft)]"
      />
      {field.failed && <SaveError what="description" onRetry={field.retry} />}
    </div>
  );
}
