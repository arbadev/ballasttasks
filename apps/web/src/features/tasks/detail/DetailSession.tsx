"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

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

interface DetailSession {
  saveStatus: SaveStatus;
  /** Every save in the panel goes through here, so the footer can say saving, saved or not saved. */
  track<T>(save: Promise<T>): Promise<T>;
  drafts: DraftStore;
  generationFailed(taskId: string): boolean;
  setGenerationFailed(taskId: string, failed: boolean): void;
}

const DetailSessionContext = createContext<DetailSession | null>(null);

/**
 * What outlives the open panel: saves still in flight, unsent drafts and failed generations.
 * It sits in TaskDetail, which the shell keeps mounted, so closing the panel or opening
 * another task loses none of it.
 */
export function DetailSessionProvider({ children }: { children: ReactNode }) {
  const [inFlight, setInFlight] = useState(0);
  const [lastFailed, setLastFailed] = useState(false);
  const [drafts] = useState(() => new DraftStore());
  const [failedGenerations, setFailedGenerations] = useState<ReadonlySet<string>>(() => new Set());

  const track = useCallback(<T,>(save: Promise<T>): Promise<T> => {
    setInFlight((n) => n + 1);
    return save.then(
      (result) => {
        setInFlight((n) => n - 1);
        setLastFailed(false);
        return result;
      },
      (error: unknown) => {
        setInFlight((n) => n - 1);
        setLastFailed(true);
        throw error;
      },
    );
  }, []);

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
      saveStatus: inFlight > 0 ? "saving" : lastFailed ? "failed" : "idle",
      track,
      drafts,
      generationFailed: (taskId) => failedGenerations.has(taskId),
      setGenerationFailed,
    }),
    [inFlight, lastFailed, track, drafts, failedGenerations, setGenerationFailed],
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
