"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Long enough to skip the keystrokes of a word, short enough to feel saved on a pause. */
export const AUTOSAVE_DELAY_MS = 400;

interface Options<T> {
  /** The value the task holds. */
  saved: T;
  save(value: T): Promise<unknown>;
  /** 0 saves on change (selects, dates); text fields pass AUTOSAVE_DELAY_MS. */
  delay?: number;
}

export interface AutosaveField<T> {
  /** What the control shows: the edit in progress, otherwise the saved value. */
  value: T;
  change(value: T): void;
  /** Saves a pending edit now: on blur. Unmounting flushes by itself. */
  flush(): void;
  /** The value a failed save tried to store; the control is already back on `saved`. */
  failed: { value: T } | null;
  retry(): void;
}

/**
 * One field of the autosaving panel. The edit is shown optimistically, saved after `delay`,
 * on blur, or when the field unmounts (the panel closing, another task opening), so typed
 * text is never dropped. A failed save rolls the control back and keeps the value for a retry.
 */
export function useAutosaveField<T>({ saved, save, delay = 0 }: Options<T>): AutosaveField<T> {
  const [draft, setDraft] = useState<{ value: T } | null>(null);
  const [failed, setFailed] = useState<{ value: T } | null>(null);
  const pending = useRef<{ value: T; timer: ReturnType<typeof setTimeout> | null } | null>(null);
  /** The save started last: where the task is headed, which `saved` only catches up to later. */
  const inFlight = useRef<{ id: number; value: T } | null>(null);
  const started = useRef(0);
  const latest = useRef({ saved, save });

  useEffect(() => {
    latest.current = { saved, save };
  });

  const flush = useCallback(() => {
    const edit = pending.current;
    if (!edit) return;
    if (edit.timer) clearTimeout(edit.timer);
    pending.current = null;

    const settleDraft = () => setDraft((d) => (d && Object.is(d.value, edit.value) ? null : d));
    const stored = inFlight.current ? inFlight.current.value : latest.current.saved;
    if (Object.is(edit.value, stored)) {
      // The save already carrying this value settles the draft when it lands; until then it shows.
      if (!inFlight.current) settleDraft();
      return;
    }

    const id = ++started.current;
    inFlight.current = { id, value: edit.value };
    /** Only the save started last has the say; an older one has been overtaken. */
    const decides = () => {
      if (inFlight.current?.id === id) inFlight.current = null;
      settleDraft();
      return id === started.current;
    };
    latest.current.save(edit.value).then(
      () => {
        if (decides()) setFailed(null);
      },
      () => {
        if (decides() && !pending.current) setFailed({ value: edit.value });
      },
    );
  }, []);

  const change = useCallback(
    (value: T) => {
      if (pending.current?.timer) clearTimeout(pending.current.timer);
      setFailed(null);
      setDraft({ value });
      pending.current = { value, timer: delay > 0 ? setTimeout(flush, delay) : null };
      if (delay === 0) flush();
    },
    [delay, flush],
  );

  const retry = useCallback(() => {
    if (!failed) return;
    setFailed(null);
    setDraft({ value: failed.value });
    pending.current = { value: failed.value, timer: null };
    flush();
  }, [failed, flush]);

  useEffect(() => flush, [flush]);

  return { value: draft ? draft.value : saved, change, flush, failed, retry };
}
