"use client";

import { Columns3, List, Menu, Plus } from "lucide-react";
import { EditProjectControl } from "@/features/projects/EditProjectControl";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { Pill } from "@/components/ui/Pill";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import type { Scope } from "../model/filter";
import type { View } from "../workspace/reducer";
import { useDirectory, useTaskCommands, useVisibleTasks, useWorkspace } from "../workspace/WorkspaceProvider";

const TITLES: Record<Scope, string> = { all: "All tasks", mine: "My tasks", overdue: "Overdue" };

const VIEWS: readonly { value: View; label: string; icon: typeof List }[] = [
  { value: "list", label: "List", icon: List },
  { value: "board", label: "Board", icon: Columns3 },
];

interface HeaderProps {
  navigationId: string;
  navigationOpen: boolean;
  onOpenNavigation: () => void;
}

export function Header({ navigationId, navigationOpen, onOpenNavigation }: HeaderProps) {
  const { state, actions } = useWorkspace();
  const { projects } = useDirectory();
  const commands = useTaskCommands();
  // The count always describes the list's filters, as in the design, even on the board.
  const loadedCount = useVisibleTasks().length;
  const count = state.page?.headerTotal ?? loadedCount;
  const project = projects.find((p) => p.id === state.query.project);

  return (
    <header className="flex flex-wrap items-center gap-4 border-b border-line px-6 pt-[18px] pb-3.5 max-md:px-4">
      <IconButton
        icon={Menu}
        label="Open navigation"
        onClick={onOpenNavigation}
        aria-expanded={navigationOpen}
        aria-controls={navigationId}
        className="md:hidden"
      />
      <div className="flex min-w-0 flex-wrap items-baseline gap-2.5">
        <span data-testid="crumb" className="font-mono text-[10.5px] tracking-[.1em] text-fg-3 uppercase">
          {project?.name ?? "Ballast"}
        </span>
        <span aria-hidden="true" className="text-fg-3">/</span>
        <h1 className="m-0 font-heading text-[length:var(--hsize)] leading-[1.1] font-[var(--hw)] tracking-[var(--hls)]">{TITLES[state.query.scope]}</h1>
        {state.load.status === "ready" && (
          <Pill>
            <span aria-live="polite">{count === 1 ? "1 task" : `${count} tasks`}</span>
          </Pill>
        )}
      </div>
      <div className="ml-auto flex items-center gap-2.5">
        {project && <EditProjectControl project={project} />}
        <SegmentedControl label="View" name="bt-view" value={state.view} options={VIEWS} onChange={actions.setView} />
        <Button icon={Plus} onClick={() => void commands.create({ title: "Untitled task" }, { open: true })}>
          New task
        </Button>
      </div>
    </header>
  );
}
