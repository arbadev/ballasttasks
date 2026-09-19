"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Task } from "../model/types";
import { useDirectory, useNow, useTaskCommands, useVisibleTasks, useWorkspace } from "../workspace/WorkspaceProvider";
import { ListLoadError } from "./ListLoadError";
import { ListSkeleton } from "./ListSkeleton";
import { QuickAdd } from "./QuickAdd";
import { TaskRow, type RowMove } from "./TaskRow";
import { rowView } from "./rowView";

const ROW_TITLE = "[data-row-title]";
const ROW_TOGGLE = "[role=checkbox]";

/** The row control that had focus when its task was toggled or opened, so focus can follow the list. */
interface PendingFocus {
  taskId: string;
  /** The status the row started from: the entry is spent once the task shows another one. */
  status: Task["status"];
  index: number;
  control: typeof ROW_TITLE | typeof ROW_TOGGLE;
}

/** The list view: quick-add, then the visible tasks in the workspace's order, one row each. */
export function ListView() {
  const { state, actions } = useWorkspace();
  const tasks = useVisibleTasks();
  const { people, projects, currentUser } = useDirectory();
  const commands = useTaskCommands();
  const now = useNow();

  const listRef = useRef<HTMLUListElement>(null);
  const quickAddRef = useRef<HTMLInputElement>(null);
  const pendingFocus = useRef<PendingFocus | null>(null);
  const [failedTitle, setFailedTitle] = useState<string | null>(null);

  const peopleById = useMemo(() => new Map(people.map((p) => [p.id, p])), [people]);
  const projectNames = useMemo(() => new Map(projects.map((p) => [p.id, p.name])), [projects]);

  const controls = (selector: string) => Array.from(listRef.current?.querySelectorAll<HTMLElement>(selector) ?? []);

  /** Remembers where focus was in a row, for when that row is about to leave the list. */
  const rememberFocus = useCallback((task: Task, index: number) => {
    const row = listRef.current?.children[index];
    const focused = document.activeElement;
    pendingFocus.current =
      row && focused && row.contains(focused) ? { taskId: task.id, status: task.status, index, control: focused.matches(ROW_TOGGLE) ? ROW_TOGGLE : ROW_TITLE } : null;
  }, []);

  // A completed row usually leaves the list (the default filter hides done tasks), and a row
  // opened in the panel can be deleted there; either way it takes the focus with it, so hand
  // the focus to the row that took its place, or to the quick-add. A row that stays keeps its
  // own focus, so the entry is dropped as soon as the toggle lands.
  useEffect(() => {
    const pending = pendingFocus.current;
    if (!pending) return;
    const row = tasks.find((t) => t.id === pending.taskId);
    if (row && row.status === pending.status) return;
    pendingFocus.current = null;
    if (row || (document.activeElement && document.activeElement !== document.body)) return;
    const candidates = Array.from(listRef.current?.querySelectorAll<HTMLElement>(pending.control) ?? []);
    (candidates[Math.min(pending.index, candidates.length - 1)] ?? quickAddRef.current)?.focus();
  }, [tasks]);

  const toggle = useCallback(
    (task: Task, index: number) => {
      rememberFocus(task, index);
      setFailedTitle(null);
      commands.toggleDone(task.id).catch(() => {
        pendingFocus.current = null;
        setFailedTitle(task.title);
      });
    },
    [commands, rememberFocus],
  );

  const move = (index: number, to: RowMove) => {
    const titles = controls(ROW_TITLE);
    if (to === "previous" && index === 0) {
      quickAddRef.current?.focus();
      return;
    }
    const target = { previous: index - 1, next: index + 1, first: 0, last: titles.length - 1 }[to];
    titles[Math.min(target, titles.length - 1)]?.focus();
  };

  if (state.load.status === "loading") return <ListSkeleton />;
  if (state.load.status === "error") return <ListLoadError message={state.load.message} onRetry={actions.reload} />;

  return (
    <div className="flex flex-col">
      <QuickAdd inputRef={quickAddRef} onAdd={(title) => commands.create({ title }, { open: false })} onLeaveDown={() => controls(ROW_TITLE)[0]?.focus()} />

      {failedTitle !== null && (
        <p role="alert" className="m-0 animate-bt-fade border-b border-line bg-danger-soft px-6 py-2 text-[12.5px] text-danger max-md:px-4">
          Could not update “{failedTitle}”. Try again.
        </p>
      )}

      {tasks.length === 0 ? (
        <p className="m-0 px-6 py-14 text-[13px] text-fg-3 max-md:px-4">No tasks match these filters.</p>
      ) : (
        <ul ref={listRef} aria-label="Tasks" className="m-0 flex list-none flex-col p-0">
          {tasks.map((task, index) => {
            const assignee = task.assignee ? (peopleById.get(task.assignee) ?? null) : null;
            return (
              <TaskRow
                key={task.id}
                task={task}
                view={rowView(task, now, index)}
                projectName={projectNames.get(task.project) ?? task.project}
                assignee={assignee}
                assigneeIsCurrentUser={assignee !== null && assignee.id === currentUser?.id}
                selected={task.id === state.selectedId}
                onOpen={() => {
                  rememberFocus(task, index);
                  actions.selectTask(task.id);
                }}
                onToggle={() => toggle(task, index)}
                onMove={(to) => move(index, to)}
              />
            );
          })}
        </ul>
      )}
    </div>
  );
}
