import { useCallback, useMemo, useRef, useState } from "react";
import { statusName } from "../model/statuses";
import type { Task, TaskStatus } from "../model/types";
import { useTaskCommands, useWorkspace } from "../workspace/WorkspaceProvider";

export interface MoveFailure {
  /** The attempt this message belongs to; the board shows older failures first. */
  move: number;
  taskId: string;
  title: string;
  /** Where the card is now that the move is undone. */
  from: TaskStatus;
  /** Where it was meant to go; Retry tries this again. */
  to: TaskStatus;
}

export interface BoardMoves {
  /** The tasks as the board shows them: a move in flight already sits in its new column. */
  tasks: Task[];
  /** Moves the card and answers with the move's number; null when there is nothing to move. */
  move(taskId: string, to: TaskStatus): number | null;
  /** Last answered ticket per task, including refusals; batched answers cannot erase each other. */
  settled: Readonly<Record<string, number>>;
  /** One per card whose move was refused and is still unanswered for, oldest attempt first. */
  failures: readonly MoveFailure[];
  dismissFailure(taskId: string): void;
  /** The last successful move, worded for a polite live region. */
  announcement: string;
}

interface Refusal {
  move: number;
  title: string;
  to: TaskStatus;
}

function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  return key in record ? Object.fromEntries(Object.entries(record).filter(([id]) => id !== key)) : record;
}

/**
 * Optimistic moves: the card changes column at once, the service is called, and a rejected
 * call puts the card back and reports the failure. The workspace stays the source of truth;
 * this only holds the statuses that are still in flight. Calls for the same task never overlap:
 * the newest queued target wins and superseded queued targets are never sent. A refusal cancels
 * that queue and restores the last saved status; Retry explicitly retries the newest target.
 *
 * Every piece of feedback is kept against the card it belongs to, never against one newest
 * attempt, and these invariants are enforced here and nowhere else:
 *
 * - a refused move always reports a failure for its own card, whatever any other card did;
 * - a card's answer only ever touches its own failure and its own announcement, so one card's
 *   success or settlement can neither silence nor outrank another card's pending answer;
 * - only that card's own next attempt, or a dismissal, clears its failure;
 * - within one card the coalescing contract is unchanged: a newer target supersedes a queued one.
 */
export function useBoardMoves(tasks: Task[]): BoardMoves {
  const commands = useTaskCommands();
  /** Every task, not only the filtered ones the board shows: a failed move outlives a filter change. */
  const all = useWorkspace().state.tasks;
  const [inFlight, setInFlight] = useState<Record<string, TaskStatus>>({});
  const [failed, setFailed] = useState<Record<string, Refusal>>({});
  const [settled, setSettled] = useState<Record<string, number>>({});
  /** The live region reads one move at a time, so its card is named with it. */
  const [announced, setAnnounced] = useState<{ taskId: string; text: string } | null>(null);
  /** Where each unsettled task is headed: the column the board shows it in, and the move that asked. */
  const target = useRef(new Map<string, { to: TaskStatus; move: number }>());
  /**
   * The tasks whose call is still out. One call per task at a time, so the service is told the
   * moves in the order the user made them and its last word is the user's last word: an older
   * answer can neither be shown nor reported over a newer move.
   */
  const calling = useRef(new Set<string>());
  const sequence = useRef(0);

  const shown = useMemo(() => tasks.map((t) => (inFlight[t.id] && inFlight[t.id] !== t.status ? { ...t, status: inFlight[t.id] } : t)), [tasks, inFlight]);

  const call = useCallback(
    function issue(taskId: string, title: string): void {
      const asked = target.current.get(taskId);
      if (!asked) return;
      calling.current.add(taskId);

      const answered = (refused: boolean) => {
        calling.current.delete(taskId);
        const newest = target.current.get(taskId) ?? asked;
        // A successful answer releases the newest queued target, but a refusal cancels it:
        // no intermediate optimistic column becomes the rollback destination.
        if (!refused && newest.move !== asked.move) {
          issue(taskId, title);
          return;
        }
        target.current.delete(taskId);
        setInFlight((current) => without(current, taskId));
        setSettled((current) => ({ ...current, [taskId]: newest.move }));
        if (!refused) return;
        // The refusal takes back this card's own announcement, and only its own.
        setAnnounced((current) => (current?.taskId === taskId ? null : current));
        setFailed((current) => ({ ...current, [taskId]: { move: newest.move, title, to: newest.to } }));
      };

      commands.move(taskId, asked.to).then(
        () => answered(false),
        () => answered(true),
      );
    },
    [commands],
  );

  const move = useCallback(
    (taskId: string, to: TaskStatus) => {
      const task = all.find((t) => t.id === taskId);
      if (!task || (target.current.get(taskId)?.to ?? task.status) === to) return null;

      const number = ++sequence.current;
      target.current.set(taskId, { to, move: number });
      setFailed((current) => without(current, taskId));
      setInFlight((current) => ({ ...current, [taskId]: to }));
      setAnnounced({ taskId, text: `Moved "${task.title}" to ${statusName(to)}.` });
      if (!calling.current.has(taskId)) call(taskId, task.title);
      return number;
    },
    [all, call],
  );

  const failures = useMemo(
    () =>
      Object.entries(failed)
        .map(([taskId, refusal]) => ({ ...refusal, taskId, from: all.find((t) => t.id === taskId)?.status }))
        .filter((failure): failure is MoveFailure => failure.from !== undefined)
        .sort((a, b) => a.move - b.move),
    [failed, all],
  );

  const dismissFailure = useCallback((taskId: string) => setFailed((current) => without(current, taskId)), []);

  return { tasks: shown, move, settled, failures, dismissFailure, announcement: announced?.text ?? "" };
}
