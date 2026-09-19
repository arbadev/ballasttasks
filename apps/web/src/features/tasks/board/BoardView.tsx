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
  /** The column whose "Add a task" was refused. */
  const [addFailedIn, setAddFailedIn] = useState<TaskStatus | null>(null);
  const grid = useRef<HTMLDivElement>(null);
  /** A card moved without a drag is remounted in its new column; focus follows it there. */
  const focusAfterMove = useRef<string | null>(null);
  /** The last card moved without a drag. A refused move remounts it once more, and focus follows it back. */
  const movedWithoutDrag = useRef<{ taskId: string; previousFailure: MoveFailure | null } | null>(null);
  const failedId = moves.failure?.taskId ?? null;

  useEffect(() => {
    if (failedId && failedId === movedWithoutDrag.current?.taskId && moves.failure !== movedWithoutDrag.current.previousFailure) {
      movedWithoutDrag.current = null;
      // Focus the user has since put somewhere else stays there.
      if (document.activeElement === document.body) focusAfterMove.current = failedId;
    }
    const id = focusAfterMove.current;
    if (!id) return;
    focusAfterMove.current = null;
    grid.current?.querySelector<HTMLElement>(`[data-card-open=${JSON.stringify(id)}]`)?.focus();
  });

  const endDrag = () => {
    setDraggedId(null);
    setOverStatus(null);
  };

  const addTask = (status: TaskStatus) => {
    setAddFailedIn(null);
    commands.create({ title: "Untitled task", status }, { open: true }).catch(() => setAddFailedIn(status));
  };

  const moveWithoutDrag = (taskId: string, to: TaskStatus) => {
    focusAfterMove.current = taskId;
    // A pending focus render can still carry the old alert when Retry is pressed.
    // Only a new refusal belongs to this attempt.
    movedWithoutDrag.current = { taskId, previousFailure: moves.failure };
    moves.move(taskId, to);
  };

  /** Retry is a button press: its alert goes away, so focus goes to the card it moves. */
  const retryMove = () => {
    if (moves.failure) moveWithoutDrag(moves.failure.taskId, moves.failure.to);
  };

  return (
    <>
      <p data-testid="board-live" aria-live="polite" className="sr-only">
        {moves.announcement}
      </p>

      {moves.failure && (
        <BoardAlert
          message={`Could not move "${moves.failure.title}" to ${statusName(moves.failure.to)}. It is back in ${statusName(moves.failure.from)}.`}
          onRetry={retryMove}
          onDismiss={moves.dismissFailure}
        />
      )}
      {addFailedIn && !moves.failure && (
        <BoardAlert message={`Could not add a task to ${statusName(addFailedIn)}.`} onRetry={() => addTask(addFailedIn)} onDismiss={() => setAddFailedIn(null)} />
      )}

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
                if (id === movedWithoutDrag.current?.taskId) movedWithoutDrag.current = null;
                if (id) moves.move(id, status.id);
                endDrag();
              }}
              onAddTask={() => addTask(status.id)}
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
                    onMove={(to) => moveWithoutDrag(task.id, to.id)}
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
