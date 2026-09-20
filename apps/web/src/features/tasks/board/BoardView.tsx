"use client";

import { useLayoutEffect, useRef, useState, type DragEvent } from "react";
import { STATUSES, statusName } from "../model/statuses";
import type { TaskStatus } from "../model/types";
import { LOAD_FAILED_WITHOUT_DETAIL, useDirectory, useNow, useTaskCommands, useVisibleTasks, useWorkspace } from "../workspace/WorkspaceProvider";
import { BoardAlert } from "./BoardAlert";
import { BoardColumn } from "./BoardColumn";
import { BoardLoadError } from "./BoardLoadError";
import { BoardSkeleton } from "./BoardSkeleton";
import { cardView } from "./cardView";
import { BOARD_GRID } from "./layout";
import { TaskCard } from "./TaskCard";
import { useBoardMoves, type MoveFailure } from "./useBoardMoves";

const DRAG_TYPE = "text/plain";

/** A move made without a drag, and where focus goes while it runs and once it has settled. */
interface FocusAfterMove {
  move: number;
  taskId: string;
  /** The column the card left, and its place in it: where focus lands if the card is gone. */
  column: TaskStatus;
  index: number;
}

/** One panel opening, and where the board has put the focus back since it closed. */
interface FocusAfterPanel {
  taskId: string;
  column: TaskStatus;
  index: number;
  opened: boolean;
  /** What the board focused on the way out: it owes another return while the focus is still there. */
  returnedTo?: HTMLElement;
}

interface BoardViewProps {
  /** Called when the board is taken off the screen still owing the keyboard somewhere to stand. */
  onReturnLost?: () => void;
}

/** The board: one column per status. It owns its loading and error states as well. */
export function BoardView({ onReturnLost }: BoardViewProps = {}) {
  const { state, actions } = useWorkspace();

  return (
    <section aria-label="Board" aria-busy={state.load.status === "loading"} className="flex min-w-0 flex-1 flex-col">
      {state.load.status === "loading" && !state.page && <BoardSkeleton />}
      {state.load.status === "error" && (
        <BoardLoadError detail={state.load.message === LOAD_FAILED_WITHOUT_DETAIL ? undefined : state.load.message} onRetry={actions.reload} />
      )}
      {(state.page || state.load.status === "ready") && <Board onReturnLost={onReturnLost} />}
    </section>
  );
}

function Board({ onReturnLost }: BoardViewProps) {
  const { state, actions } = useWorkspace();
  const { people, projects, currentUser } = useDirectory();
  const commands = useTaskCommands();
  const now = useNow();
  // Every status is a column, so the Status filter does not apply here, as in the design.
  const moves = useBoardMoves(useVisibleTasks({ applyStatus: false }));
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [overStatus, setOverStatus] = useState<TaskStatus | null>(null);
  /**
   * Each column adds one task at a time, and columns do not wait for each other: a column is
   * busy while its call is out, and stays busy once refused, so the refusal keeps its place on
   * the screen until the user retries or dismisses it.
   */
  const [adding, setAdding] = useState<Partial<Record<TaskStatus, "pending" | "failed">>>({});
  const grid = useRef<HTMLDivElement>(null);
  /**
   * The card moved without a drag. It is remounted in its new column, and again if the move is
   * refused, so focus follows it until the move has settled: it is never left on the body.
   */
  const focusAfterMove = useRef<FocusAfterMove | null>(null);
  const focusAfterPanel = useRef<FocusAfterPanel | null>(null);
  /** Removing a focused alert does not emit blur; an ordinary focus change does. */
  const focusedFailure = useRef<{ taskId: string; column: TaskStatus } | null>(null);

  const cardButton = (taskId: string) => grid.current?.querySelector<HTMLElement>(`[data-card-open=${JSON.stringify(taskId)}]`) ?? null;
  const cardsIn = (status: TaskStatus) => [...(grid.current?.querySelectorAll<HTMLElement>(`[data-column=${JSON.stringify(status)}] [data-card-open]`) ?? [])];
  const columnHeading = (status: TaskStatus) => grid.current?.querySelector<HTMLElement>(`[data-column=${JSON.stringify(status)}] [data-column-heading]`) ?? null;
  const columnAdd = (status: TaskStatus) => grid.current?.querySelector<HTMLElement>(`[data-column=${JSON.stringify(status)}] [data-column-add]`) ?? null;

  // Retiring an alert and handing off its focus are one visible commit. A passive effect
  // leaves BODY focused after the canonical query has already reported itself settled.
  useLayoutEffect(() => {
    const focused = focusedFailure.current;
    if (focused && !moves.failures.some((failure) => failure.taskId === focused.taskId)) {
      focusedFailure.current = null;
      if (document.activeElement === document.body) {
        const status = state.tasks.find((task) => task.id === focused.taskId)?.status ?? focused.column;
        (cardButton(focused.taskId) ?? columnHeading(status))?.focus();
      }
    }

    const pending = focusAfterMove.current;
    if (!pending) return;
    const done = moves.settled[pending.taskId] === pending.move;
    if (done) focusAfterMove.current = null;
    // Focus the user has since put somewhere else stays there.
    if (document.activeElement !== document.body) return;

    const card = cardButton(pending.taskId);
    if (card) {
      card.focus();
      return;
    }
    if (!done) return;
    // The move took the card off the board: focus what took its place in the column it left.
    const left = cardsIn(pending.column);
    (left[Math.max(0, Math.min(pending.index, left.length - 1))] ?? columnHeading(pending.column))?.focus();
  });

  // The modal returns to a connected opener itself. A detail edit can remount that card in
  // another column, and a save still in flight, or the canonical query it triggers, can do so
  // long after the panel has gone. So the board keeps owing a return for as long as the focus
  // is where it put it, and stops owing one as soon as the user moves it themselves (the blur
  // below). No focus moves while a panel is selected, nor for an obsolete selection.
  useLayoutEffect(() => {
    const pending = focusAfterPanel.current;
    if (!pending) return;
    if (state.selectedId === pending.taskId) {
      pending.opened = true;
      return;
    }
    if (!pending.opened) return;
    const active = document.activeElement;
    if (state.selectedId !== null || (active !== document.body && active !== pending.returnedTo)) {
      focusAfterPanel.current = null;
      return;
    }
    if (active !== document.body) return;
    const neighbours = cardsIn(pending.column);
    const target = cardButton(pending.taskId) ?? neighbours[Math.min(pending.index, neighbours.length - 1)] ?? columnHeading(pending.column);
    if (!target) return;
    pending.returnedTo = target;
    target.focus();
  });

  // A board that is taken away — the last task of a project deleted from its panel — takes the
  // card, neighbour or heading it was returning to with it. Only the view that replaces it can
  // carry the keyboard on from there, so the shell is told the return is now its own.
  useLayoutEffect(
    () => () => {
      if (focusAfterPanel.current || focusAfterMove.current) onReturnLost?.();
    },
    [onReturnLost],
  );

  const endDrag = () => {
    setDraggedId(null);
    setOverStatus(null);
  };

  const addTask = (status: TaskStatus) => {
    setAdding((current) => ({ ...current, [status]: "pending" }));
    commands.create({ title: "Untitled task", status }, { open: true }).then(
      () => setAdding((current) => ({ ...current, [status]: undefined })),
      () => setAdding((current) => ({ ...current, [status]: "failed" })),
    );
  };

  const moveWithoutDrag = (taskId: string, from: TaskStatus, to: TaskStatus) => {
    const index = cardsIn(from).findIndex((c) => c.dataset.cardOpen === taskId);
    const move = moves.move(taskId, to);
    if (move !== null) focusAfterMove.current = { move, taskId, column: from, index };
  };

  /** Retry is a button press: its alert goes away, so focus goes to the card it moves. */
  const retryMove = (failure: MoveFailure) => moveWithoutDrag(failure.taskId, failure.from, failure.to);

  /**
   * Retrying and dismissing take the pressed button off the screen, so focus goes first to what
   * the alert was about: the card, the column it is in, or the "Add a task" that was refused.
   */
  const dismissMove = (failure: MoveFailure) => {
    (cardButton(failure.taskId) ?? columnHeading(failure.from))?.focus();
    moves.dismissFailure(failure.taskId);
  };

  const retryAdd = (status: TaskStatus) => {
    columnAdd(status)?.focus();
    addTask(status);
  };

  const dismissAdd = (status: TaskStatus) => {
    columnAdd(status)?.focus();
    setAdding((current) => ({ ...current, [status]: undefined }));
  };

  return (
    <>
      <p data-testid="board-live" aria-live="polite" className="sr-only">
        {moves.announcement}
      </p>

      {moves.failures.map((failure) => (
        <BoardAlert
          key={failure.taskId}
          message={`Could not move "${failure.title}". It is back in ${statusName(failure.from)}.`}
          retryLabel={`Retry moving "${failure.title}"`}
          dismissLabel={`Dismiss: could not move "${failure.title}"`}
          onRetry={() => retryMove(failure)}
          onDismiss={() => dismissMove(failure)}
          onFocus={() => (focusedFailure.current = { taskId: failure.taskId, column: failure.from })}
          onBlur={() => (focusedFailure.current = null)}
        />
      ))}
      {STATUSES.filter((status) => adding[status.id] === "failed").map((status) => (
        <BoardAlert
          key={status.id}
          message={`Could not add a task to ${status.name}.`}
          retryLabel={`Retry adding a task to ${status.name}`}
          dismissLabel={`Dismiss: could not add a task to ${status.name}`}
          onRetry={() => retryAdd(status.id)}
          onDismiss={() => dismissAdd(status.id)}
        />
      ))}

      <div
        ref={grid}
        className={BOARD_GRID}
        onBlurCapture={(event) => {
          // Taking the focused card off the board emits no blur, and leaves a detached target
          // where one is emitted at all. Anything else is the user leaving — a Tab, a click on
          // another control or on nothing at all — and the board stops owing them a return.
          if (focusAfterPanel.current?.returnedTo === event.target && event.target.isConnected) focusAfterPanel.current = null;
        }}
      >
        {STATUSES.map((status, position) => {
          const tasks = moves.tasks.filter((t) => t.status === status.id);
          return (
            <BoardColumn
              key={status.id}
              status={status}
              count={state.page?.columns?.[status.id] ?? tasks.length}
              visibleCount={tasks.length}
              dropTarget={overStatus === status.id}
              onDragOver={(event: DragEvent<HTMLElement>) => {
                event.preventDefault();
                setOverStatus(status.id);
              }}
              onDrop={(event: DragEvent<HTMLElement>) => {
                event.preventDefault();
                const id = draggedId ?? event.dataTransfer.getData(DRAG_TYPE);
                // A dragged card is where the pointer put it: this move does not take focus.
                if (id === focusAfterMove.current?.taskId) focusAfterMove.current = null;
                if (id) moves.move(id, status.id);
                endDrag();
              }}
              adding={adding[status.id]}
              onAddTask={() => {
                if (!adding[status.id]) addTask(status.id);
              }}
            >
              {tasks.map((task, index) => (
                <li key={task.id}>
                  <TaskCard
                    task={task}
                    view={cardView(task, now)}
                    index={index}
                    projectName={projects.find((p) => p.id === task.project)?.name ?? task.project}
                    assignee={people.find((p) => p.id === task.assignee) ?? null}
                    assigneeIsCurrentUser={task.assignee !== null && task.assignee === currentUser?.id}
                    selected={state.selectedId === task.id}
                    dragging={draggedId === task.id}
                    previous={STATUSES[position - 1] ?? null}
                    next={STATUSES[position + 1] ?? null}
                    onOpen={() => {
                      const opener = cardButton(task.id);
                      focusAfterPanel.current = opener?.closest("article")?.contains(document.activeElement)
                        ? { taskId: task.id, column: status.id, index, opened: false }
                        : null;
                      actions.selectTask(task.id);
                    }}
                    onMove={(to) => moveWithoutDrag(task.id, status.id, to.id)}
                    onDragStart={(event) => {
                      event.dataTransfer.setData(DRAG_TYPE, task.id);
                      event.dataTransfer.effectAllowed = "move";
                      setDraggedId(task.id);
                    }}
                    onDragEnd={endDrag}
                  />
                </li>
              ))}
            </BoardColumn>
          );
        })}
      </div>
    </>
  );
}
