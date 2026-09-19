"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

export type SaveStatus = "idle" | "saving" | "failed";

/** Text typed into the step and comment boxes but not sent yet, kept per task. */
class DraftStore {
  private readonly texts = new Map<string, string>();
  get(key: string): string {
    return this.texts.get(key) ?? "";
  }
  set(key: string, text: string): void {
    if (text) this.texts.set(key, text);
    else this.texts.delete(key);
  }
}

/** What one composer is waiting on: the text it sent, and whether that send came back failed. */
export interface Submission {
  text: string;
  failed: boolean;
}

/** The one submission each step and comment box is waiting on, kept per task. */
class SubmissionStore {
  private readonly pending = new Map<string, Submission>();
  get(key: string): Submission | null {
    return this.pending.get(key) ?? null;
  }
  set(key: string, submission: Submission | null): void {
    if (submission) this.pending.set(key, submission);
    else this.pending.delete(key);
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
  drafts: DraftStore;
  submissions: SubmissionStore;
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
  const [drafts] = useState(() => new DraftStore());
  const [submissions] = useState(() => new SubmissionStore());
  const [failedGenerations, setFailedGenerations] = useState<ReadonlySet<string>>(() => new Set());

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
      drafts,
      submissions,
      generationFailed: (taskId) => failedGenerations.has(taskId),
      setGenerationFailed,
    }),
    [saves, track, drafts, submissions, failedGenerations, setGenerationFailed],
  );

  return <DetailSessionContext.Provider value={value}>{children}</DetailSessionContext.Provider>;
}

export function useDetailSession(): DetailSession {
  const session = useContext(DetailSessionContext);
  if (!session) throw new Error("useDetailSession must be used inside <DetailSessionProvider>.");
  return session;
}

/** A text box whose unsent content survives the panel closing: [text, setText]. */
export function useDraft(key: string): [string, (text: string) => void] {
  const { drafts } = useDetailSession();
  const [text, setText] = useState(() => drafts.get(key));
  const update = useCallback(
    (next: string) => {
      drafts.set(key, next);
      setText(next);
    },
    [drafts, key],
  );
  return [text, update];
}

export interface Composer {
  /** What the box holds now. */
  text: string;
  setText(text: string): void;
  /** The submission this box is waiting on: running, or failed and kept for a retry. */
  pending: Submission | null;
  /** Sends what is in the box. Ignored while this box is waiting on something. */
  submit(): void;
  retry(): void;
  dismiss(): void;
}

/**
 * A step or comment box and the one submission it is waiting on, both kept under the task's
 * own key so they come back with the task. The box sends one thing at a time: a send that
 * fails is held until it is retried or dismissed, and meanwhile the box stays the user's to
 * type in. Text is only ever taken out of the box when this composer put it there and nothing
 * has been typed since, so no send can erase what the user wrote or post the same thing twice.
 */
export function useComposer(key: string, send: (text: string) => Promise<unknown>): Composer {
  const { drafts, submissions } = useDetailSession();
  const [text, setStoredText] = useDraft(key);
  const [pending, setPendingState] = useState(() => submissions.get(key));
  const restored = useRef<string | null>(null);
  const latest = useRef(send);

  useEffect(() => {
    latest.current = send;
  });

  const setPending = useCallback(
    (next: Submission | null) => {
      submissions.set(key, next);
      setPendingState(next);
    },
    [submissions, key],
  );

  const run = useCallback(
    (value: string) => {
      setPending({ text: value, failed: false });
      latest.current(value).then(
        () => {
          setPending(null);
          if (restored.current === null) return;
          restored.current = null;
          setStoredText("");
        },
        () => {
          setPending({ text: value, failed: true });
          if (drafts.get(key)) return;
          restored.current = value;
          setStoredText(value);
        },
      );
    },
    [drafts, key, setPending, setStoredText],
  );

  const setText = useCallback(
    (next: string) => {
      restored.current = null;
      setStoredText(next);
    },
    [setStoredText],
  );

  const submit = useCallback(() => {
    if (submissions.get(key)) return;
    const value = drafts.get(key).trim();
    if (!value) return;
    restored.current = null;
    setStoredText("");
    run(value);
  }, [drafts, submissions, key, run, setStoredText]);

  const retry = useCallback(() => {
    const held = submissions.get(key);
    if (!held?.failed) return;
    run(held.text);
  }, [submissions, key, run]);

  const dismiss = useCallback(() => {
    if (!submissions.get(key)?.failed) return;
    restored.current = null;
    setPending(null);
  }, [submissions, key, setPending]);

  return { text, setText, pending, submit, retry, dismiss };
}
