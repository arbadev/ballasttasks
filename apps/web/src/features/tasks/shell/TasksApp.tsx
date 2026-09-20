"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { EmptyProject, useEmptyProject } from "@/features/projects/EmptyProject";
import { BoardView } from "../board/BoardView";
import { TaskDetail } from "../detail/TaskDetail";
import { ListView } from "../list/ListView";
import { WorkspaceProvider, useWorkspace } from "../workspace/WorkspaceProvider";
import { AttentionStrip } from "./AttentionStrip";
import { FilterToolbar } from "./FilterToolbar";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { TaskPagination } from "./TaskPagination";

/** The tasks application: workspace state plus the shell that mounts the three views. */
export function TasksApp() {
  return (
    <WorkspaceProvider>
      <Shell />
    </WorkspaceProvider>
  );
}

function Shell() {
  const { state } = useWorkspace();
  const navigationId = useId();
  const [navigationOpen, setNavigationOpen] = useState(false);
  const closeNavigation = useCallback(() => setNavigationOpen(false), []);
  const emptyProject = useEmptyProject();
  /** Set only when the empty-project state saved the first task: the list it becomes takes the focus. */
  const [focusQuickAdd, setFocusQuickAdd] = useState(false);
  const quickAddFocused = useCallback(() => setFocusQuickAdd(false), []);
  /** The other way round: the board went away owing the keyboard a place, and this state replaced it. */
  const [focusFirstTask, setFocusFirstTask] = useState(false);
  const firstTaskFocused = useCallback(() => setFocusFirstTask(false), []);
  const returnLost = useRef(false);
  const boardReturnLost = useCallback(() => {
    returnLost.current = true;
  }, []);

  // Deleting a project's last task from its panel takes the board away with the card, neighbour
  // or heading it was returning to, and nothing in it outlives that. The invitation that replaces
  // it takes the focus over, and only where the removal left the focus nowhere at all.
  useLayoutEffect(() => {
    if (returnLost.current && emptyProject && document.activeElement === document.body) setFocusFirstTask(true);
    returnLost.current = false;
  }, [emptyProject]);

  useEffect(() => {
    if (!navigationOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeNavigation();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigationOpen, closeNavigation]);

  return (
    <div className="flex min-h-dvh bg-bg text-fg">
      {navigationOpen && (
        <div data-testid="drawer-backdrop" onClick={closeNavigation} className="fixed inset-0 z-30 animate-bt-fade bg-backdrop backdrop-blur-[6px] md:hidden" />
      )}
      <Sidebar id={navigationId} open={navigationOpen} onNavigate={closeNavigation} />
      <main className="flex min-h-dvh min-w-0 flex-1 flex-col">
        <Header navigationId={navigationId} navigationOpen={navigationOpen} onOpenNavigation={() => setNavigationOpen(true)} />
        <FilterToolbar />
        <AttentionStrip />
        {/* A project with no tasks invites the first one. Each view owns its loading and error states. */}
        {emptyProject ? (
          <EmptyProject
            project={emptyProject}
            onFirstTask={() => setFocusQuickAdd(state.view === "list")}
            focusFirstTask={focusFirstTask}
            onFirstTaskFocused={firstTaskFocused}
          />
        ) : state.view === "list" ? (
          <ListView focusQuickAdd={focusQuickAdd} onQuickAddFocused={quickAddFocused} />
        ) : (
          <BoardView onReturnLost={boardReturnLost} />
        )}
        <TaskPagination />
      </main>
      <TaskDetail />
    </div>
  );
}
