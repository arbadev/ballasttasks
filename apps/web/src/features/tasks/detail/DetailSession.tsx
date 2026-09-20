"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { StepOrderStore } from "./stepOrderStore";
import { AutosaveMachine, type FieldOptions } from "./autosaveMachine";

export type SaveStatus = "idle" | "saving" | "failed";

/** The send a step or comment box is waiting on. */
interface Sending {
  text: string;
  /** The send came back refused; the text is kept here so a Retry can send exactly it. */
  failed: boolean;
  /** The box holds this send's own text — left there by an in-place box or put back by a
   *  refusal — and nothing has been typed over it since. */
  restored: boolean;
}

/** One step or comment box: what is typed in it, and the one send it is waiting on. */
interface ComposerState {
  text: string;
  sending: Sending | null;
}

const EMPTY_COMPOSER: ComposerState = { text: "", sending: null };

/**
 * Every step and comment box, under its own key. One place holds both what is typed and what
 * is in flight, so a box that is closed and opened again — a different React instance — reads
 * and writes the same record, and a send that answers while the panel is shut is seen by the
 * box that comes back. Read with `useSyncExternalStore`, as the step generation is.
 */
class ComposerStore {
  private state: ReadonlyMap<string, ComposerState> = new Map();
  private readonly listeners = new Set<() => void>();

  get(key: string): ComposerState {
    return this.state.get(key) ?? EMPTY_COMPOSER;
  }

  update(key: string, step: (current: ComposerState) => ComposerState): void {
    const after = step(this.get(key));
    if (after === this.get(key)) return;
    const next = new Map(this.state);
    if (after.text === "" && after.sending === null) next.delete(key);
    else next.set(key, after);
    this.state = next;
    this.listeners.forEach((listener) => listener());
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
}

interface DetailSession {
  /** What the footer says about one task, and only that task. */
  saveStatus(taskId: string): SaveStatus;
  /**
   * Every save in the panel goes through here, under the id of the task it is saving, so the
   * footer can say saving, saved or not saved about exactly the task the reader is looking at.
   * A save that fails leaves that task alone on "not saved" until one of its own succeeds;
   * no other task's outcome clears it, and none of them inherits it.
   */
  track<T>(taskId: string, save: Promise<T>): Promise<T>;
  composers: ComposerStore;
  stepOrders: StepOrderStore;
  /** One date field owner per task, including its pending write and exact-null recovery. */
  dateField(taskId: string, options: FieldOptions<string | null>): AutosaveMachine<string | null>;
  generationFailed(taskId: string): boolean;
  setGenerationFailed(taskId: string, failed: boolean): void;
}

/** One task's saves: how many are running, and whether the last one to answer failed. */
interface TaskSaves {
  inFlight: number;
  failed: boolean;
}

const SETTLED: TaskSaves = { inFlight: 0, failed: false };

const DetailSessionContext = createContext<DetailSession | null>(null);

/**
 * What outlives the open panel: saves still in flight, unsent drafts and failed generations.
 * It sits in TaskDetail, which the shell keeps mounted, so closing the panel or opening
 * another task loses none of it.
 */
export function DetailSessionProvider({ children }: { children: ReactNode }) {
  const [saves, setSaves] = useState<ReadonlyMap<string, TaskSaves>>(() => new Map());
  const [composers] = useState(() => new ComposerStore());
  const [stepOrders] = useState(() => new StepOrderStore());
  const [dateFields] = useState(() => new Map<string, AutosaveMachine<string | null>>());
  const [failedGenerations, setFailedGenerations] = useState<ReadonlySet<string>>(() => new Set());

  const dateField = useCallback((taskId: string, options: FieldOptions<string | null>) => {
    let field = dateFields.get(taskId);
    if (!field) {
      field = new AutosaveMachine(options);
      dateFields.set(taskId, field);
    }
    return field;
  }, [dateFields]);

  const record = useCallback((taskId: string, step: (current: TaskSaves) => TaskSaves) => {
    setSaves((current) => {
      const next = new Map(current);
      const after = step(current.get(taskId) ?? SETTLED);
      if (after.inFlight === 0 && !after.failed) next.delete(taskId);
      else next.set(taskId, after);
      return next;
    });
  }, []);

  const track = useCallback(
    <T,>(taskId: string, save: Promise<T>): Promise<T> => {
      record(taskId, (s) => ({ ...s, inFlight: s.inFlight + 1 }));
      return save.then(
        (result) => {
          record(taskId, (s) => ({ inFlight: s.inFlight - 1, failed: false }));
          return result;
        },
        (error: unknown) => {
          record(taskId, (s) => ({ inFlight: s.inFlight - 1, failed: true }));
          throw error;
        },
      );
    },
    [record],
  );

  const setGenerationFailed = useCallback((taskId: string, failed: boolean) => {
    setFailedGenerations((current) => {
      if (current.has(taskId) === failed) return current;
      const next = new Set(current);
      if (failed) next.add(taskId);
      else next.delete(taskId);
      return next;
    });
  }, []);

  const value = useMemo<DetailSession>(
    () => ({
      saveStatus: (taskId) => {
        const task = saves.get(taskId);
        if (!task) return "idle";
        return task.inFlight > 0 ? "saving" : task.failed ? "failed" : "idle";
      },
      track,
      composers,
      stepOrders,
      dateField,
      generationFailed: (taskId) => failedGenerations.has(taskId),
      setGenerationFailed,
    }),
    [saves, track, composers, stepOrders, dateField, failedGenerations, setGenerationFailed],
  );

  return <DetailSessionContext.Provider value={value}>{children}</DetailSessionContext.Provider>;
}

export function useDetailSession(): DetailSession {
  const session = useContext(DetailSessionContext);
  if (!session) throw new Error("useDetailSession must be used inside <DetailSessionProvider>.");
  return session;
}

export interface Composer {
  /** What the box holds now. */
  text: string;
  setText(text: string): void;
  /** A send is running: the box takes one at a time and says so while it waits. */
  sending: boolean;
  /** The text of a send that was refused, kept for Retry until it is retried or dismissed. */
  failed: string | null;
  /** This box cannot take a send: one is running, or one was refused and is still held. */
  busy: boolean;
  /** Sends what is in the box. Does nothing while this box is `busy`. An in-place box keeps
   *  the trimmed text it sent; every other box empties for the next draft. */
  submit(): void;
  retry(): void;
  dismiss(): void;
}

/**
 * A step or comment box and the one send it is waiting on, both kept under the task's own key
 * so they come back with the task and survive the panel closing mid-send. The box sends one
 * thing at a time: while a send runs the box says so and takes no second one, and a send that
 * is refused is held, still blocking, until it is retried or dismissed — there is no implicit
 * way past it. The box stays the user's to type in throughout; text is only ever taken back
 * out of it when the send itself put it there and nothing has been typed over it since, however
 * many refusals that took, so no send can erase what the user wrote or post the same thing
 * twice. A box that edits in place (`editsInPlace`) keeps what it sent on screen instead of
 * emptying for the next draft, and gives it up only when that same send lands untouched.
 */
export function useComposer(key: string, send: (text: string) => Promise<unknown>, editsInPlace = false): Composer {
  const { composers } = useDetailSession();
  const read = useCallback(() => composers.get(key), [composers, key]);
  const subscribe = useCallback((listener: () => void) => composers.subscribe(listener), [composers]);
  const state = useSyncExternalStore(subscribe, read, read);
  const latest = useRef(send);

  useEffect(() => {
    latest.current = send;
  });

  const run = useCallback(
    (value: string, owned = false) => {
      composers.update(key, (c) => ({ ...c, sending: { text: value, failed: false, restored: owned || (c.sending?.restored ?? false) } }));
      latest.current(value).then(
        () =>
          composers.update(key, (c) => ({
            text: c.sending?.restored && c.text === c.sending.text ? "" : c.text,
            sending: null,
          })),
        () =>
          composers.update(key, (c) => {
            // Still this send's text in the box: either it was empty, or the send itself or an
            // earlier refusal put the text there and nothing has been typed over it since.
            const restored = c.text === "" || (c.sending?.restored === true && c.text === value);
            return { text: restored ? value : c.text, sending: { text: value, failed: true, restored } };
          }),
      );
    },
    [composers, key],
  );

  const setText = useCallback(
    (next: string) => {
      // Typing makes the box the user's again, whatever a failed send left in it.
      composers.update(key, (c) => ({ text: next, sending: c.sending?.restored ? { ...c.sending, restored: false } : c.sending }));
    },
    [composers, key],
  );

  const submit = useCallback(() => {
    const current = composers.get(key);
    if (current.sending) return;
    const value = current.text.trim();
    if (!value) return;
    composers.update(key, (c) => ({ ...c, text: editsInPlace ? value : "" }));
    run(value, editsInPlace);
  }, [composers, key, run, editsInPlace]);

  const retry = useCallback(() => {
    const held = composers.get(key).sending;
    if (!held?.failed) return;
    run(held.text);
  }, [composers, key, run]);

  const dismiss = useCallback(() => {
    composers.update(key, (c) => (c.sending?.failed ? { ...c, sending: null } : c));
  }, [composers, key]);

  return {
    text: state.text,
    setText,
    sending: state.sending !== null && !state.sending.failed,
    failed: state.sending?.failed ? state.sending.text : null,
    busy: state.sending !== null,
    submit,
    retry,
    dismiss,
  };
}
