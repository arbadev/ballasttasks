"use client";

import { useEffect, useRef, useState, type DragEvent } from "react";
import { Button } from "@/components/ui/Button";
import { STATUSES, statusName } from "../model/statuses";
import type { TaskStatus } from "../model/types";
import { useDirectory, useNow, useTaskCommands, useVisibleTasks, useWorkspace } from "../workspace/WorkspaceProvider";
import { BoardAlert } from "./BoardAlert";
import { BoardColumn } from "./BoardColumn";
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

/** The board: one column per status. It owns its loading and error states as well. */
export function BoardView() {
  const { state, actions } = useWorkspace();

  return (
    <section aria-label="Board" className="flex min-w-0 flex-1 flex-col">
      {state.load.status === "loading" && <BoardSkeleton />}
      {state.load.status === "error" && (
        <div role="alert" className="flex flex-col items-start gap-3 px-8 py-14 text-[13px] text-fg-2 max-md:px-4">
          <p className="m-0">
            Could not load the board. <span className="text-fg-3">{state.load.message}</span>
          </p>
          <Button variant="ghost" onClick={actions.reload} className="border border-line bg-card text-fg-2">
            Retry
          </Button>
        </div>
      )}
      {state.load.status === "ready" && <Board />}
    </section>
  );
}

function Board() {
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

  const cardButton = (taskId: string) => grid.current?.querySelector<HTMLElement>(`[data-card-open=${JSON.stringify(taskId)}]`) ?? null;
  const cardsIn = (status: TaskStatus) => [...(grid.current?.querySelectorAll<HTMLElement>(`[data-column=${JSON.stringify(status)}] [data-card-open]`) ?? [])];
  const columnHeading = (status: TaskStatus) => grid.current?.querySelector<HTMLElement>(`[data-column=${JSON.stringify(status)}] [data-column-heading]`) ?? null;
  const columnAdd = (status: TaskStatus) => grid.current?.querySelector<HTMLElement>(`[data-column=${JSON.stringify(status)}] [data-column-add]`) ?? null;

  useEffect(() => {
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

      <div ref={grid} className={BOARD_GRID}>
        {STATUSES.map((status, position) => {
          const tasks = moves.tasks.filter((t) => t.status === status.id);
          return (
            <BoardColumn
              key={status.id}
              status={status}
              count={tasks.length}
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
                    onOpen={() => actions.selectTask(task.id)}
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
