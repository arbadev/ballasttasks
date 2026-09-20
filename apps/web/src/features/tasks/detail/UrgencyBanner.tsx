"use client";

import { Sparkles, User } from "lucide-react";
import { cn } from "@/lib/cn";
import { dayFrom } from "../model/due";
import type { Task } from "../model/types";
import { useDirectory, useNow, useTaskCommands } from "../workspace/WorkspaceProvider";
import { PanelButton } from "./controls";
import { useDetailSession } from "./DetailSession";
import { bannerFor } from "./model/banner";
import { useDueField } from "./useDueField";
import type { StepGenerationView } from "./useStepGeneration";

const TONES = {
  danger: "bg-danger/12 text-danger",
  warn: "bg-warn/12 text-warn",
  info: "bg-info/12 text-info",
};

/** Why this task needs attention, with the one-click ways out of it. */
export function UrgencyBanner({ task, generation }: { task: Task; generation: StepGenerationView }) {
  const now = useNow();
  const { currentUser } = useDirectory();
  const commands = useTaskCommands();
  const { track } = useDetailSession();
  // The quick reschedules write the same date the properties box owns, so they queue behind
  // whatever it has in flight and report a refusal through its one inline message and Retry.
  const due = useDueField(task);
  const banner = bannerFor(task, now, generation.generation !== null);
  if (!banner) return null;

  const save = (change: Promise<unknown>) => void track(task.id, change).catch(() => {});
  const today = dayFrom(0, now);
  // A week out from the due date, or from today when that date has already passed.
  const weekOut = dayFrom(7, now, task.due && task.due > today ? task.due : today);

  return (
    <div data-testid="detail-banner" className={cn("flex animate-[bt-in_.3s_var(--ease)] flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-5 py-2.5 max-md:px-4", TONES[banner.tone])}>
      <span aria-hidden="true" className={cn("size-2 flex-none rounded-full bg-current", banner.blink && "animate-bt-blink")} />
      <p className="m-0 flex-auto text-[13px] font-medium">{banner.text}</p>
      <div className="ml-auto flex flex-none flex-wrap gap-1.5">
        {banner.canAssign && currentUser && (
          <PanelButton variant="banner" icon={User} iconSize={12} iconStroke={2.2} onClick={() => save(commands.update(task.id, { assignee: currentUser.id }))}>
            Assign to me
          </PanelButton>
        )}
        {banner.canDraft && (
          <PanelButton variant="banner" icon={Sparkles} iconSize={12} onClick={generation.start}>
            Break it into steps
          </PanelButton>
        )}
        {banner.canReschedule && (
          <>
            <PanelButton variant="banner" onClick={() => due.store(dayFrom(1, now), "Due date moved to tomorrow")}>
              Due tomorrow
            </PanelButton>
            <PanelButton variant="banner" onClick={() => due.store(weekOut, "Due date moved a week out")}>
              +1 week
            </PanelButton>
          </>
        )}
      </div>
    </div>
  );
}
