"use client";

import { ArrowLeft, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { STATUSES } from "../model/statuses";
import type { Task } from "../model/types";
import { useDirectory } from "../workspace/WorkspaceProvider";
import { taskKey } from "./model/taskKey";

const STATUS_TONES = {
  muted: "bg-fg-3/14 text-fg-3",
  accent: "bg-acc/14 text-acc",
  warn: "bg-warn/14 text-warn",
  ok: "bg-ok/14 text-ok",
};

const SQUARE_BUTTON =
  "size-8 flex-none cursor-pointer place-items-center rounded-bt-sm border border-line bg-card text-fg-2 transition-colors duration-[160ms] ease-bt hover:bg-card-2 hover:text-fg pointer-coarse:size-11";

/** Where the task lives (key, project, status) and the way out of the panel. */
export function DetailHeader({ task, onClose }: { task: Task; onClose: () => void }) {
  const { projects } = useDirectory();
  const status = STATUSES.find((s) => s.id === task.status) ?? STATUSES[0];

  return (
    <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-3 max-md:px-4">
      {/* Full-screen below md: a back control where a thumb expects it, instead of the corner X. */}
      <button type="button" aria-label="Back to tasks" title="Back to tasks" onClick={onClose} className={cn(SQUARE_BUTTON, "grid md:hidden")}>
        <ArrowLeft aria-hidden="true" size={15} strokeWidth={2} />
      </button>
      <span className="font-mono text-[11px] text-fg-3">{taskKey(task.id)}</span>
      <span aria-hidden="true" className="text-line-2">
        /
      </span>
      <span data-testid="detail-project" className="font-mono text-[10.5px] tracking-[.08em] text-fg-3 uppercase">
        {projects.find((p) => p.id === task.project)?.name ?? task.project}
      </span>
      <span data-testid="detail-status" className={cn("inline-flex h-[22px] items-center gap-1.5 rounded-bt-sm px-2 text-[11.5px] font-medium", STATUS_TONES[status.tone])}>
        <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
        {status.name}
      </span>
      <button type="button" aria-label="Close task" title="Close task" onClick={onClose} className={cn(SQUARE_BUTTON, "ml-auto hidden md:grid")}>
        <X aria-hidden="true" size={15} strokeWidth={2} />
      </button>
    </div>
  );
}
