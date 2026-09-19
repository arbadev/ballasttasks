"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Long enough to skip the keystrokes of a word, short enough to feel saved on a pause. */
export const AUTOSAVE_DELAY_MS = 400;

interface Options<T> {
  /** The value the task holds, as the service last confirmed it. */
  saved: T;
  save(value: T): Promise<unknown>;
  /**
   * Which values the field can store, asked again when the field settles (blur, unmount)
   * rather than autosaving after a pause. An emptied number box is never storable; an emptied
   * date is, but only once the user has left it, because a date reports empty mid-edit.
   */
  savable?(value: T, settling: boolean): boolean;
  /** 0 saves on change (selects, dates); text fields pass AUTOSAVE_DELAY_MS. */
  delay?: number;
}

export interface AutosaveField<T> {
  /** What the control shows: the edit in progress, otherwise the saved value. */
  value: T;
  change(value: T): void;
  /** Settles the field now: on blur, and when it unmounts (the panel closing, a task switch). */
  flush(): void;
  /** The value a failed save tried to store; the control is already back on `saved`. */
  failed: { value: T } | null;
  retry(): void;
}

/** Everything the field knows about where its value is, in one place. */
interface Machine<T> {
  /** Typed, waiting for the debounce or a flush to hand it to a save. */
  pending: { value: T; timer: ReturnType<typeof setTimeout> | null } | null;
  /** The save running now, and the ticket that tells its answer from a stale one. */
  inFlight: { ticket: number; value: T } | null;
  /** The value waiting for `inFlight` to answer, so the service is written to in order. */
  queued: { value: T } | null;
  tickets: number;
}

/**
 * One field of the autosaving panel. The edit is shown optimistically, saved after `delay`,
 * on blur, or when the field unmounts, so typed text is never dropped.
 *
 * The state above obeys five rules, all of them enforced in `start` and `commit` alone:
 *
 * 1. A draft is cleared only by the service's answer about exactly that value — success (the
 *    task now holds it) or failure (the control rolls back and says so). It is never dropped
 *    because some other value looks equal, so the control cannot fall back to text the
 *    service has not caught up to.
 * 2. A save is never skipped because its value matches one already running; it is queued
 *    behind it. Only an edit that ends where the confirmed value already is, with nothing on
 *    its way to the service, writes nothing.
 * 3. Saves are serialised: one runs at a time, the next starts when it has answered. The
 *    service therefore applies the edits in the order they were made, and an older answer can
 *    never land on top of a newer one.
 * 4. A successful save clears this field's failure, and a failure is recorded only when it is
 *    the last word: nothing newer typed or queued behind it.
 * 5. A value the field declares unsavable is not a save at all: it never runs and never clears
 *    the draft, so a half-typed value stays as typed. `flush` asks once more, as settling, and
 *    puts the control back on the confirmed value when the answer is still no.
 */
export function useAutosaveField<T>({ saved, save, savable, delay = 0 }: Options<T>): AutosaveField<T> {
  const [draft, setDraft] = useState<{ value: T } | null>(null);
  const [failed, setFailed] = useState<{ value: T } | null>(null);
  const machine = useRef<Machine<T>>({ pending: null, inFlight: null, queued: null, tickets: 0 });
  const latest = useRef({ saved, save, savable });

  useEffect(() => {
    latest.current = { saved, save, savable };
  });

  const start = useCallback((first: T) => {
    const state = machine.current;

    function run(value: T) {
      const ticket = ++state.tickets;
      state.inFlight = { ticket, value };

      const answered = (ok: boolean) => {
        if (state.inFlight?.ticket !== ticket) return;
        state.inFlight = null;
        const next = state.queued;
        state.queued = null;

        if (ok) setFailed(null);
        if (!next && !state.pending) {
          setDraft((d) => (d && Object.is(d.value, value) ? null : d));
          if (!ok) setFailed({ value });
        }
        if (next) run(next.value);
      };

      latest.current.save(value).then(
        () => answered(true),
        () => answered(false),
      );
    }

    run(first);
  }, []);

  /** Hands the pending edit to a save. False when the value is one the field cannot store. */
  const commit = useCallback(
    (settling: boolean) => {
      const state = machine.current;
      const edit = state.pending;
      if (!edit) return true;
      if (edit.timer) clearTimeout(edit.timer);

      if (latest.current.savable?.(edit.value, settling) === false) {
        state.pending = { value: edit.value, timer: null };
        return false;
      }

      state.pending = null;
      if (!state.inFlight && !state.queued && Object.is(edit.value, latest.current.saved)) {
        setDraft((d) => (d && Object.is(d.value, edit.value) ? null : d));
        return true;
      }
      if (state.inFlight) state.queued = { value: edit.value };
      else start(edit.value);
      return true;
    },
    [start],
  );

  const flush = useCallback(() => {
    if (commit(true)) return;
    machine.current.pending = null;
    setDraft(null);
  }, [commit]);

  const change = useCallback(
    (value: T) => {
      const state = machine.current;
      if (state.pending?.timer) clearTimeout(state.pending.timer);
      setFailed(null);
      setDraft({ value });
      state.pending = { value, timer: delay > 0 ? setTimeout(() => commit(false), delay) : null };
      if (delay === 0) commit(false);
    },
    [delay, commit],
  );

  const retry = useCallback(() => {
    if (!failed) return;
    setFailed(null);
    setDraft({ value: failed.value });
    machine.current.pending = { value: failed.value, timer: null };
    commit(true);
  }, [failed, commit]);

  useEffect(() => flush, [flush]);

  return { value: draft ? draft.value : saved, change, flush, failed, retry };
}
