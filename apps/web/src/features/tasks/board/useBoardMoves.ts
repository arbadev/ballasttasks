import { useCallback, useMemo, useRef, useState } from "react";
import { statusName } from "../model/statuses";
import type { Task, TaskStatus } from "../model/types";
import { useTaskCommands, useWorkspace } from "../workspace/WorkspaceProvider";

export interface MoveFailure {
  /** Identifies the user attempt this message belongs to. */
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
  failure: MoveFailure | null;
  dismissFailure(): void;
  /** The last successful move, worded for a polite live region. */
  announcement: string;
}

/**
 * Optimistic moves: the card changes column at once, the service is called, and a rejected
 * call puts the card back and reports the failure. The workspace stays the source of truth;
 * this only holds the statuses that are still in flight. Calls for the same task never overlap:
 * the newest queued target wins and superseded queued targets are never sent. A refusal cancels
 * that queue and restores the last saved status; Retry explicitly retries the newest target.
 */
export function useBoardMoves(tasks: Task[]): BoardMoves {
  const commands = useTaskCommands();
  /** Every task, not only the filtered ones the board shows: a failed move outlives a filter change. */
  const all = useWorkspace().state.tasks;
  const [inFlight, setInFlight] = useState<Record<string, TaskStatus>>({});
  const [failed, setFailed] = useState<Omit<MoveFailure, "from"> | null>(null);
  const [settled, setSettled] = useState<Record<string, number>>({});
  const [announcement, setAnnouncement] = useState("");
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
        setInFlight((current) => Object.fromEntries(Object.entries(current).filter(([id]) => id !== taskId)));
        setSettled((current) => ({ ...current, [taskId]: newest.move }));
        // An older task's answer must not replace the newest attempt's feedback.
        if (!refused || newest.move !== sequence.current) return;
        setAnnouncement("");
        setFailed({ move: newest.move, taskId, title, to: newest.to });
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
      setFailed(null);
      setInFlight((current) => ({ ...current, [taskId]: to }));
      setAnnouncement(`Moved "${task.title}" to ${statusName(to)}.`);
      if (!calling.current.has(taskId)) call(taskId, task.title);
      return number;
    },
    [all, call],
  );

  const failure = useMemo(() => {
    const from = failed && all.find((t) => t.id === failed.taskId)?.status;
    return failed && from ? { ...failed, from } : null;
  }, [failed, all]);

  const dismissFailure = useCallback(() => setFailed(null), []);

  return { tasks: shown, move, settled, failure, dismissFailure, announcement };
}
