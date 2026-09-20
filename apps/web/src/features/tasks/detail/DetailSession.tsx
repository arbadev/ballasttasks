"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import type { Task } from "../model/types";
import { TaskReadbackError, type AcknowledgedWrite } from "../services/types";
import { AutosaveMachine, type FieldOptions } from "./autosaveMachine";

export type SaveStatus = "idle" | "saving" | "refreshing" | "refresh" | "failed";

/** The send a step or comment box is waiting on. */
interface Sending {
  text: string;
  /** The send or its readback needs explicit recovery; acknowledged selects read-only recovery. */
  failed: boolean;
  /** The write was acknowledged: recovery must only read, even if another read fails. */
  acknowledged: boolean;
  /** The row the server stored for it: seeing that row on the task is what ends the recovery. */
  saved: AcknowledgedWrite | null;
  /** This send's failure put its text back in the box, and nothing has been typed since. */
  restored: boolean;
}

/** One step or comment box: what is typed in it, and the one send it is waiting on. */
interface ComposerState {
  text: string;
  sending: Sending | null;
}

const EMPTY_COMPOSER: ComposerState = { text: "", sending: null };

/** The two boxes a task has. A composer's key names its box and the task the box belongs to. */
export type ComposerKind = AcknowledgedWrite["kind"];

const COMPOSER_KINDS: readonly ComposerKind[] = ["comment", "step"];

const composerKey = (kind: ComposerKind, taskId: string) => `${kind}:${taskId}`;

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

  /** The acknowledged appends this task's boxes are still waiting to see on the task. */
  acknowledged(taskId: string): readonly Sending[] {
    return COMPOSER_KINDS.flatMap((kind) => {
      const sending = this.get(composerKey(kind, taskId)).sending;
      return sending?.failed && sending.acknowledged ? [sending] : [];
    });
  }

  /** That one held recovery is over: the box takes sends again and keeps whatever is typed in it. */
  settle(key: string, held: Sending): boolean {
    let settled = false;
    this.update(key, (c) => {
      if (c.sending !== held) return c;
      settled = true;
      return { ...c, sending: null };
    });
    return settled;
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
   * A refused save leaves that task on "not saved"; an acknowledged write whose readback
   * failed says "saved · reload needed". No other task's outcome clears or inherits it, and a
   * read-only phase never speaks for a write: it leaves "not saved" exactly as it found it.
   */
  track<T>(taskId: string, save: Promise<T>, phase?: "write" | "refresh"): Promise<T>;
  composers: ComposerStore;
  /**
   * The row an acknowledged append created is on the canonical detail the panel is showing, so
   * that exact recovery is over: the box is freed, and the task stops asking for a reload once
   * no box is still waiting to see its own row. A genuinely unsaved write keeps "not saved".
   */
  settleReadback(key: string, held: Sending): void;
  /** One date field owner per task, including its pending write and exact-null recovery. */
  dateField(taskId: string, options: FieldOptions<string | null>): AutosaveMachine<string | null>;
  generationFailed(taskId: string): boolean;
  setGenerationFailed(taskId: string, failed: boolean): void;
}

/** One task's saves: how many are running, and whether the last one to answer failed. */
interface TaskSaves {
  inFlight: number;
  refreshing: number;
  failure: "failed" | "refresh" | null;
}

const SETTLED: TaskSaves = { inFlight: 0, refreshing: 0, failure: null };

const DetailSessionContext = createContext<DetailSession | null>(null);

/**
 * What outlives the open panel: saves still in flight, unsent drafts and failed generations.
 * It sits in TaskDetail, which the shell keeps mounted, so closing the panel or opening
 * another task loses none of it.
 */
export function DetailSessionProvider({ children }: { children: ReactNode }) {
  const [saves, setSaves] = useState<ReadonlyMap<string, TaskSaves>>(() => new Map());
  const [composers] = useState(() => new ComposerStore());
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
      if (after.inFlight === 0 && !after.failure) next.delete(taskId);
      else next.set(taskId, after);
      return next;
    });
  }, []);

  const track = useCallback(
    <T,>(taskId: string, save: Promise<T>, phase: "write" | "refresh" = "write"): Promise<T> => {
      const reading = phase === "refresh" ? 1 : 0;
      const settled = (s: TaskSaves, outcome: TaskSaves["failure"]): TaskSaves["failure"] =>
        phase === "refresh" && s.failure === "failed" ? "failed" : outcome;
      record(taskId, (s) => ({ ...s, inFlight: s.inFlight + 1, refreshing: s.refreshing + reading }));
      return save.then(
        (result) => {
          record(taskId, (s) => ({ inFlight: s.inFlight - 1, refreshing: s.refreshing - reading, failure: settled(s, null) }));
          return result;
        },
        (error: unknown) => {
          record(taskId, (s) => ({ inFlight: s.inFlight - 1, refreshing: s.refreshing - reading, failure: settled(s, reading || error instanceof TaskReadbackError ? "refresh" : "failed") }));
          throw error;
        },
      );
    },
    [record],
  );

  const settleReadback = useCallback(
    (key: string, held: Sending) => {
      const saved = held.saved;
      if (!saved || !composers.settle(key, held)) return;
      if (composers.acknowledged(saved.taskId).length > 0) return;
      record(saved.taskId, (s) => (s.failure === "refresh" ? { ...s, failure: null } : s));
    },
    [composers, record],
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
        return task.inFlight > 0 ? task.refreshing === task.inFlight ? "refreshing" : "saving" : task.failure ?? "idle";
      },
      track,
      composers,
      settleReadback,
      dateField,
      generationFailed: (taskId) => failedGenerations.has(taskId),
      setGenerationFailed,
    }),
    [saves, track, composers, settleReadback, dateField, failedGenerations, setGenerationFailed],
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
  refreshing: boolean;
  /** Acknowledged write: show read-only recovery, never a refused-send Retry or Dismiss. */
  refreshRequired: boolean;
  /** The original text awaiting either send retry or acknowledged read recovery. */
  failed: string | null;
  /** This box cannot take a send while its current write or readback needs recovery. */
  busy: boolean;
  /** Sends what is in the box. Does nothing while this box is `busy`. */
  submit(): void;
  retry(): void;
  dismiss(): void;
}

/**
 * A step or comment box and the one send it is waiting on, both kept under the task's own key
 * so they come back with the task and survive the panel closing mid-send. A known acknowledged
 * write switches permanently to read-only recovery; its saved text is never an unsent draft,
 * and the recovery ends by itself as soon as the task's own canonical detail shows the very row
 * the server stored — whichever reload brought it — never on a summary or anyone else's row.
 * The box sends one thing at a time: while a send runs the box says so and takes no second one.
 * A send that is refused is held, still blocking, until it is retried or dismissed — there is no implicit
 * way past it. The box stays the user's to type in throughout; text is only ever taken back
 * out of it when a failure put it there and nothing has been typed over it since, however
 * many refusals that took, so no send can erase what the user wrote or post the same thing
 * twice.
 */
export function useComposer(task: Task, kind: ComposerKind, send: (text: string) => Promise<unknown>, refresh: () => Promise<unknown>): Composer {
  const { composers, settleReadback } = useDetailSession();
  const key = composerKey(kind, task.id);
  const read = useCallback(() => composers.get(key), [composers, key]);
  const subscribe = useCallback((listener: () => void) => composers.subscribe(listener), [composers]);
  const state = useSyncExternalStore(subscribe, read, read);
  const latest = useRef({ send, refresh });

  useEffect(() => {
    latest.current = { send, refresh };
  });

  // The rows this box's own canonical detail shows. A list summary carries no children, so it
  // proves nothing and is never read as proof.
  const shown = useMemo(
    () =>
      task.detailLoaded === false
        ? null
        : new Set(
            kind === "comment"
              ? task.activity.flatMap((entry) => (entry.type === "comment" && entry.id ? [entry.id] : []))
              : task.steps.map((step) => step.id),
          ),
    [task, kind],
  );

  const held = state.sending;
  useEffect(() => {
    if (!held?.failed || !held.saved || !shown) return;
    const saved = held.saved;
    if (saved.taskId !== task.id || saved.kind !== kind || !shown.has(saved.childId)) return;
    settleReadback(key, held);
  }, [held, shown, task.id, kind, key, settleReadback]);

  const run = useCallback(
    (value: string, acknowledged = false, saved: AcknowledgedWrite | null = null) => {
      composers.update(key, (c) => ({ ...c, sending: { text: value, failed: false, acknowledged, saved, restored: c.sending?.restored ?? false } }));
      const pending = acknowledged ? latest.current.refresh() : latest.current.send(value);
      pending.then(
        () =>
          composers.update(key, (c) => ({
            text: c.sending?.restored && c.text === c.sending.text ? "" : c.text,
            sending: null,
          })),
        (error: unknown) =>
          composers.update(key, (c) => {
            if (acknowledged || error instanceof TaskReadbackError) {
              // The original text is saved, not an unsent draft. Retire only text a prior
              // genuine refusal restored; independent edits remain the user's throughout.
              const text = c.sending?.restored && c.text === value ? "" : c.text;
              const stored = saved ?? (error instanceof TaskReadbackError ? error.saved : null);
              return { text, sending: { text: value, failed: true, acknowledged: true, saved: stored, restored: false } };
            }
            const restored = c.text === "" || (c.sending?.restored === true && c.text === value);
            return { text: restored ? value : c.text, sending: { text: value, failed: true, acknowledged: false, saved: null, restored } };
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
    composers.update(key, (c) => ({ ...c, text: "" }));
    run(value);
  }, [composers, key, run]);

  const retry = useCallback(() => {
    const held = composers.get(key).sending;
    if (!held?.failed) return;
    run(held.text, held.acknowledged, held.saved);
  }, [composers, key, run]);

  const dismiss = useCallback(() => {
    composers.update(key, (c) => (c.sending?.failed && !c.sending.acknowledged ? { ...c, sending: null } : c));
  }, [composers, key]);

  return {
    text: state.text,
    setText,
    sending: state.sending !== null && !state.sending.failed && !state.sending.acknowledged,
    refreshing: state.sending !== null && !state.sending.failed && state.sending.acknowledged,
    refreshRequired: state.sending?.acknowledged ?? false,
    failed: state.sending?.failed ? state.sending.text : null,
    busy: state.sending !== null,
    submit,
    retry,
    dismiss,
  };
}
