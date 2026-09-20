import type { ProjectTone } from "@/features/tasks/model/types";
import { cn } from "@/lib/cn";
import { PROJECT_TONES } from "../model/rules";
import { ProjectDot } from "./ProjectDot";

const TONE_NAMES: Record<ProjectTone, string> = { accent: "Lime", info: "Blue", ok: "Green", warn: "Amber", muted: "Grey" };

export function ProjectColour({ id, tone, setTone, pending }: { id: string; tone: ProjectTone; setTone: (tone: ProjectTone) => void; pending: boolean }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span id={`${id}-tone-label`} className="text-[11.5px] text-fg-3">
        Colour
      </span>
      <div role="radiogroup" aria-labelledby={`${id}-tone-label`} className="flex h-[34px] gap-0.5 rounded-bt border border-line bg-card p-[3px] pointer-coarse:h-11">
        {PROJECT_TONES.map((option) => (
          <label
            key={option}
            title={TONE_NAMES[option]}
            className={cn(
              // The radio itself is invisible, so the label carries its focus ring.
              "relative grid aspect-square h-full cursor-pointer place-items-center rounded-[calc(var(--r)-3px)] transition-colors duration-[160ms] ease-bt has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-acc has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50",
              option === tone ? "bg-card-2 shadow-1 ring-1 ring-line-2 ring-inset" : "hover:bg-card-2",
            )}
          >
            <input
              type="radio"
              name={`${id}-tone`}
              value={option}
              aria-label={TONE_NAMES[option]}
              checked={option === tone}
              onChange={() => setTone(option)}
              disabled={pending}
              className="absolute size-0 opacity-0"
            />
            <ProjectDot tone={option} className={cn("transition-[width,height] duration-[160ms] ease-bt", option === tone ? "size-3" : "size-2")} />
          </label>
        ))}
      </div>
    </div>
  );
}
