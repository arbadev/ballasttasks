import type { ProjectTone } from "@/features/tasks/model/types";
import { cn } from "@/lib/cn";

const TONES: Record<ProjectTone, string> = {
  accent: "bg-acc",
  muted: "bg-fg-3",
  info: "bg-info",
  ok: "bg-ok",
  warn: "bg-warn",
};

/** The small square that identifies a project by colour, in the sidebar and wherever it is named. */
export function ProjectDot({ tone, className = "size-2" }: { tone: ProjectTone; className?: string }) {
  return <span aria-hidden="true" className={cn("flex-none rounded-bt-sm", TONES[tone], className)} />;
}
