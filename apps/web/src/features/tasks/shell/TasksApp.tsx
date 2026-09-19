"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/Button";
import { EmptyProject, useEmptyProject } from "@/features/projects/EmptyProject";
import { BoardView } from "../board/BoardView";
import { TaskDetail } from "../detail/TaskDetail";
import { ListView } from "../list/ListView";
import { WorkspaceProvider, useWorkspace } from "../workspace/WorkspaceProvider";
import { AttentionStrip } from "./AttentionStrip";
import { FilterToolbar } from "./FilterToolbar";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

/** The tasks application: workspace state plus the shell that mounts the three views. */
export function TasksApp() {
  return (
    <WorkspaceProvider>
      <Shell />
    </WorkspaceProvider>
  );
}

function Shell() {
  const { state, actions } = useWorkspace();
  const navigationId = useId();
  const [navigationOpen, setNavigationOpen] = useState(false);
  const closeNavigation = useCallback(() => setNavigationOpen(false), []);
  const emptyProject = useEmptyProject();

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
        {/* A project with no tasks invites the first one. Otherwise the list draws its own loading
            and error states; the board still uses the shell's. */}
        {emptyProject ? (
          <EmptyProject project={emptyProject} />
        ) : state.view === "list" ? (
          <ListView />
        ) : (
          <>
            {state.load.status === "loading" && (
              <p role="status" className="px-6 py-14 text-[13px] text-fg-3 max-md:px-4">
                Loading tasks…
              </p>
            )}
            {state.load.status === "error" && (
              <div role="alert" className="flex flex-col items-start gap-3 px-6 py-14 text-[13px] text-fg-2 max-md:px-4">
                <p className="m-0">
                  Could not load the tasks. <span className="text-fg-3">{state.load.message}</span>
                </p>
                <Button variant="ghost" onClick={actions.reload} className="border border-line bg-card text-fg-2">
                  Retry
                </Button>
              </div>
            )}
            {state.load.status === "ready" && <BoardView />}
          </>
        )}
      </main>
      <TaskDetail />
    </div>
  );
}
