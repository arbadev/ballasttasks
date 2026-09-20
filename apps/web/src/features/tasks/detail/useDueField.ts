"use client";

import type { Task } from "../model/types";
import { useTaskCommands } from "../workspace/WorkspaceProvider";
import { useDetailSession } from "./DetailSession";
import { AUTOSAVE_DELAY_MS, useAutosaveField, type AutosaveField } from "./useAutosaveField";

/**
 * One task's due date and everything that writes it: the date box, "Clear date", and the
 * urgency banner's quick reschedules. They share the session-owned field, so the writes are
 * serialized and the newest wins whatever order the service answers in, and one inline message
 * with a Retry that carries the rejected value speaks for all of them.
 *
 * A date input reports an empty value while one of its segments is being retyped, so an empty
 * box is never a date the task can hold: leaving the field puts the stored date back, and
 * removing the date is its own action.
 */
export function useDueField(task: Task): AutosaveField<string | null> {
  const commands = useTaskCommands();
  const { track, dateField } = useDetailSession();
  const options = {
    saved: task.due,
    savable: (v: string | null) => v !== null,
    save: (v: string | null, note?: string) => track(task.id, commands.update(task.id, { due: v }, note)),
  };
  return useAutosaveField({ ...options, owner: dateField(task.id, options), delay: AUTOSAVE_DELAY_MS });
}
