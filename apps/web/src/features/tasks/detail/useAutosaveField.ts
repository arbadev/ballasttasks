"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { AutosaveMachine, type FieldOptions } from "./autosaveMachine";

/** Long enough to skip the keystrokes of a word, short enough to feel saved on a pause. */
export const AUTOSAVE_DELAY_MS = 400;

interface Options<T> extends FieldOptions<T> {
  /** 0 saves on change; text and date fields pass AUTOSAVE_DELAY_MS. */
  delay?: number;
  /** A session-owned field survives panel close/switch; otherwise the owner is this mount. */
  owner?: AutosaveMachine<T>;
}

export interface AutosaveField<T> {
  value: T;
  change(value: T): void;
  /** Flush complete edits on blur and unmount; incomplete typing never authorizes a write. */
  flush(): void;
  /** Explicitly stores a value (including null), through the same serialized save path. */
  store(value: T): void;
  failed: { value: T } | null;
  retry(): void;
}

/** A subscribed view of one field machine: there is no mount-local draft or recovery mirror. */
export function useAutosaveField<T>({ saved, save, savable, delay = 0, owner }: Options<T>): AutosaveField<T> {
  const [local] = useState(() => owner ?? new AutosaveMachine({ saved, save, savable }));
  const machine = owner ?? local;
  const view = useSyncExternalStore(machine.subscribe, machine.getSnapshot, machine.getSnapshot);

  useEffect(() => {
    machine.configure({ saved, save, savable });
  }, [machine, saved, save, savable]);
  useEffect(() => machine.flush, [machine]);

  const change = useCallback((value: T) => machine.change(value, delay), [machine, delay]);
  return {
    value: view.draft ? view.draft.value : saved,
    change,
    flush: machine.flush,
    store: machine.store,
    failed: view.failed,
    retry: machine.retry,
  };
}
