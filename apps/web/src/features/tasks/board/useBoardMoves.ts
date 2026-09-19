import { useCallback, useMemo, useRef, useState } from "react";
import { statusName } from "../model/statuses";
import type { Task, TaskStatus } from "../model/types";
import { useTaskCommands, useWorkspace } from "../workspace/WorkspaceProvider";

export interface MoveFailure {
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
  /** Moving to the column the card is in does nothing. */
  move(taskId: string, to: TaskStatus): void;
  failure: MoveFailure | null;
  retry(): void;
  dismissFailure(): void;
  /** The last successful move, worded for a polite live region. */
  announcement: string;
}

/**
 * Optimistic moves: the card changes column at once, the service is called, and a rejected
 * call puts the card back and reports the failure. The workspace stays the source of truth;
 * this only holds the statuses that are still in flight.
 */
export function useBoardMoves(tasks: Task[]): BoardMoves {
  const commands = useTaskCommands();
  /** Every task, not only the filtered ones the board shows: a failed move outlives a filter change. */
  const all = useWorkspace().state.tasks;
  const [inFlight, setInFlight] = useState<Record<string, TaskStatus>>({});
  const [failed, setFailed] = useState<Omit<MoveFailure, "from"> | null>(null);
  const [announcement, setAnnouncement] = useState("");
  /** The newest move per task, so an older answer never clears a newer move. */
  const latest = useRef(new Map<string, number>());
  const sequence = useRef(0);

  const shown = useMemo(() => tasks.map((t) => (inFlight[t.id] && inFlight[t.id] !== t.status ? { ...t, status: inFlight[t.id] } : t)), [tasks, inFlight]);

  const move = useCallback(
    (taskId: string, to: TaskStatus) => {
      const task = all.find((t) => t.id === taskId);
      if (!task || (inFlight[taskId] ?? task.status) === to) return;

      const ticket = ++sequence.current;
      latest.current.set(taskId, ticket);
      setFailed(null);
      setInFlight((current) => ({ ...current, [taskId]: to }));
      setAnnouncement(`Moved "${task.title}" to ${statusName(to)}.`);

      const settle = () => {
        if (latest.current.get(taskId) !== ticket) return false;
        latest.current.delete(taskId);
        setInFlight((current) => Object.fromEntries(Object.entries(current).filter(([id]) => id !== taskId)));
        return true;
      };
      commands.move(taskId, to).then(settle, () => {
        if (!settle()) return;
        setAnnouncement("");
        setFailed({ taskId, title: task.title, to });
      });
    },
    [all, inFlight, commands],
  );

  const failure = useMemo(() => {
    const from = failed && all.find((t) => t.id === failed.taskId)?.status;
    return failed && from ? { ...failed, from } : null;
  }, [failed, all]);

  const retry = useCallback(() => {
    if (failure) move(failure.taskId, failure.to);
  }, [failure, move]);

  const dismissFailure = useCallback(() => setFailed(null), []);

  return { tasks: shown, move, failure, retry, dismissFailure, announcement };
}
