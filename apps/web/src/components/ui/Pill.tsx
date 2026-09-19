import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface PillProps {
  children: ReactNode;
  /** `outline` is the quiet bordered count; the rest are filled status tones. */
  tone?: "outline" | "neutral" | "accent" | "danger" | "warn" | "info" | "ok";
  className?: string;
}

const TONES = {
  outline: "border border-line px-[7px] py-0.5 text-[11px] text-fg-3",
  neutral: "h-5 bg-card-2 px-[7px] text-[10.5px] tracking-[.04em] text-fg-2",
  accent: "h-5 bg-acc-soft px-[7px] text-[10.5px] tracking-[.04em] text-acc",
  danger: "h-5 bg-danger-soft px-[7px] text-[10.5px] tracking-[.04em] text-danger",
  warn: "h-5 bg-warn-soft px-[7px] text-[10.5px] tracking-[.04em] text-warn",
  info: "h-5 bg-info-soft px-[7px] text-[10.5px] tracking-[.04em] text-info",
  ok: "h-5 bg-ok-soft px-[7px] text-[10.5px] tracking-[.04em] text-ok",
};

/** A small monospace badge: counts, priorities, statuses. */
export function Pill({ children, tone = "outline", className }: PillProps) {
  return <span className={cn("inline-flex items-center rounded-r-sm font-mono", TONES[tone], className)}>{children}</span>;
}
