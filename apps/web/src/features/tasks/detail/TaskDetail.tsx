"use client";

import { X } from "lucide-react";
import { useEffect } from "react";
import { IconButton } from "@/components/ui/IconButton";
import { useWorkspace } from "../workspace/WorkspaceProvider";

/**
 * PLACEHOLDER, owned by the task-detail worker. It shows that a task is selected and closes
 * on Escape or the close button; the real side panel replaces everything in here.
 */
export function TaskDetail() {
  const { state, actions } = useWorkspace();
  const task = state.tasks.find((t) => t.id === state.selectedId) ?? null;

  useEffect(() => {
    if (!task) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") actions.clearSelection();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [task, actions]);

  if (!task) return null;

  return (
    <div className="fixed inset-0 z-50 flex animate-bt-fade justify-end bg-backdrop backdrop-blur-[6px]" onClick={actions.clearSelection}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={task.title}
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-[min(920px,100%)] animate-bt-panel flex-col gap-3 border-l border-line bg-panel p-6 shadow-2 max-md:p-4"
      >
        <div className="flex items-center gap-3">
          <h2 className="m-0 min-w-0 flex-1 truncate font-heading text-lg font-[var(--hw)] tracking-[var(--hls)]">{task.title}</h2>
          <IconButton icon={X} label="Close task" onClick={actions.clearSelection} />
        </div>
        <p className="m-0 text-[13px] text-fg-3">The task detail panel goes here.</p>
      </div>
    </div>
  );
}
