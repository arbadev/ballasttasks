"use client";

import { Activity, Check, CircleAlert, List, LogOut, User, type LucideIcon } from "lucide-react";
import { useAuthService } from "@/app/providers";
import type { ReactNode } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { IconButton } from "@/components/ui/IconButton";
import { NewProjectControl } from "@/features/projects/NewProjectControl";
import { ProjectDot } from "@/features/projects/ui/ProjectDot";
import { cn } from "@/lib/cn";
import { sidebarCounts } from "../model/counts";
import type { Scope } from "../model/filter";
import { useDirectory, useNow, useWorkspace } from "../workspace/WorkspaceProvider";

/** The assistant is a system actor, not a teammate: it never appears in the People list. */
const ASSISTANT_ID = "ai";

const SCOPES: readonly { scope: Scope; label: string; icon: LucideIcon }[] = [
  { scope: "all", label: "All tasks", icon: List },
  { scope: "mine", label: "My tasks", icon: User },
  { scope: "overdue", label: "Overdue", icon: CircleAlert },
];

interface SidebarProps {
  id: string;
  /** Below the `md` breakpoint the sidebar is a drawer; this is whether it is showing. */
  open: boolean;
  /** Called after a choice is made, so the drawer can close. */
  onNavigate: () => void;
}

export function Sidebar({ id, open, onNavigate }: SidebarProps) {
  const auth = useAuthService();
  const { state, actions } = useWorkspace();
  const { people, projects, currentUser } = useDirectory();
  const now = useNow();
  const loaded = state.load.status === "ready";
  const counts = sidebarCounts(state.tasks, { now, currentUserId: currentUser?.id ?? "" });
  const scopeCount = { all: counts.all, mine: counts.mine, overdue: counts.overdue };

  return (
    <aside
      id={id}
      aria-label="Workspace"
      data-open={open}
      className={cn(
        "flex h-dvh w-60 flex-none flex-col overflow-auto border-r border-line bg-panel",
        "max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-40 max-md:shadow-2 md:sticky md:top-0",
        open ? "max-md:animate-bt-fade" : "max-md:hidden",
      )}
    >
      <div className="flex items-center gap-2.5 px-[18px] pt-[18px] pb-3.5">
        <span className="grid size-[22px] place-items-center rounded-bt-sm bg-acc text-acc-fg shadow-glow">
          <Check aria-hidden="true" size={12} strokeWidth={3.5} />
        </span>
        <span className="flex items-baseline gap-[5px] font-heading text-base font-[var(--hw)] tracking-[var(--hls)]">
          Ballast <span className="font-sans text-sm font-normal text-fg-3">Tasks</span>
        </span>
      </div>

      <nav aria-label="Views" className="flex flex-col gap-0.5 px-2.5 py-1.5">
        {SCOPES.map(({ scope, label, icon: Icon }) => (
          <NavButton
            key={scope}
            active={state.query.scope === scope}
            onClick={() => {
              actions.selectScope(scope);
              onNavigate();
            }}
            className="h-[34px]"
          >
            <Icon aria-hidden="true" size={15} strokeWidth={2} />
            <span className="flex-1">{label}</span>
            <Count danger={scope === "overdue"}>{loaded ? scopeCount[scope] : ""}</Count>
          </NavButton>
        ))}
      </nav>

      <SectionLabel className="pt-4" action={<NewProjectControl onCreated={onNavigate} className="-my-1.5 -mr-1 pointer-coarse:-my-3.5" />}>
        Projects
      </SectionLabel>
      <nav aria-label="Projects" className="flex flex-col gap-0.5 px-2.5">
        {projects.map((project) => (
          <NavButton
            key={project.id}
            active={state.query.project === project.id}
            onClick={() => {
              actions.toggleProject(project.id);
              onNavigate();
            }}
            className="h-8"
          >
            <ProjectDot tone={project.tone} />
            <span className="flex-1">{project.name}</span>
            <Count>{loaded ? (counts.byProject[project.id] ?? 0) : ""}</Count>
          </NavButton>
        ))}
      </nav>

      <SectionLabel className="pt-[18px]">People</SectionLabel>
      <ul aria-label="People" className="flex flex-col gap-2 px-[18px]">
        {people
          .filter((person) => person.id !== ASSISTANT_ID)
          .map((person) => (
            <li key={person.id} className="flex items-center gap-2.5">
              <Avatar initials={person.initials} tone={person.id === currentUser?.id ? "accent" : "neutral"} />
              <span className="flex-1 truncate text-[13px] text-fg-2">{person.name}</span>
              <span className="font-mono text-[10.5px] text-fg-3">{person.role}</span>
            </li>
          ))}
      </ul>

      <div data-testid="current-user" className="mt-auto flex items-center gap-2.5 border-t border-line px-[18px] py-3.5">
        {currentUser && (
          <>
            <Avatar initials={currentUser.initials} tone="accent" size={28} />
            <div className="flex min-w-0 flex-1 flex-col leading-[1.3]">
              <span className="truncate text-[13px] font-medium">{currentUser.name}</span>
              <span className="font-mono text-[10.5px] text-fg-3">{currentUser.role}</span>
            </div>
          </>
        )}
        {auth && currentUser && <IconButton icon={LogOut} label="Sign out" onClick={() => auth.logout()} />}
        <IconButton icon={Activity} label="System status" href="/status" className="ml-auto" />
      </div>
    </aside>
  );
}

function NavButton({ active, onClick, className, children }: { active: boolean; onClick: () => void; className: string; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex cursor-pointer items-center gap-2.5 rounded-bt-sm px-2.5 text-left text-[13px] font-medium transition-colors duration-[160ms] ease-bt hover:bg-card-2 hover:text-fg pointer-coarse:min-h-11",
        active ? "bg-card-2 text-fg" : "text-fg-2",
        className,
      )}
    >
      {children}
    </button>
  );
}

function Count({ danger = false, children }: { danger?: boolean; children: ReactNode }) {
  return <span className={cn("font-mono text-[11px]", danger ? "text-danger" : "text-fg-3")}>{children}</span>;
}

function SectionLabel({ className, action, children }: { className: string; action?: ReactNode; children: ReactNode }) {
  return (
    <div className={cn("flex items-center px-[18px] pb-1.5 font-mono text-[10.5px] tracking-[.1em] text-fg-3 uppercase", className)}>
      <span className="flex-1">{children}</span>
      {action}
    </div>
  );
}
