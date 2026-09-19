import { cn } from "@/lib/cn";

interface AvatarProps {
  initials: string;
  /** Names the avatar for assistive tech. Omit when the name is already next to it. */
  name?: string;
  /** `accent` is the current user, `solid` the assistant, `neutral` everyone else. */
  tone?: "neutral" | "accent" | "solid";
  size?: 24 | 26 | 28;
}

const TONES = {
  neutral: "bg-card-2 text-fg-2",
  accent: "bg-acc-soft text-acc",
  solid: "bg-acc text-acc-fg",
};

const SIZES = {
  24: "size-6 text-[9.5px] tracking-[.02em]",
  26: "size-[26px] text-[10px] tracking-[.02em]",
  28: "size-7 text-[10.5px]",
};

export function Avatar({ initials, name, tone = "neutral", size = 24 }: AvatarProps) {
  const className = cn("grid flex-none place-items-center rounded-bt-av border border-line font-semibold", TONES[tone], SIZES[size]);
  return name ? (
    <span role="img" aria-label={name} title={name} className={className}>
      {initials}
    </span>
  ) : (
    <span aria-hidden="true" className={className}>
      {initials}
    </span>
  );
}
