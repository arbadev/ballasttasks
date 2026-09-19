import type { LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** `primary` is the accent call to action; `ghost` is a quiet text button. */
  variant?: "primary" | "ghost";
  icon?: LucideIcon;
}

const VARIANTS = {
  primary:
    "h-[34px] gap-2 rounded-bt bg-acc px-3.5 text-[13px] font-semibold text-acc-fg shadow-glow transition-[transform,filter] hover:-translate-y-px hover:brightness-[1.08] active:translate-y-0 active:scale-[.98]",
  ghost:
    "h-7 gap-1.5 rounded-bt-sm bg-transparent px-2.5 text-[12.5px] text-fg-3 transition-colors hover:bg-card hover:text-fg",
};

export function Button({ variant = "primary", icon: Icon, className, children, ...props }: ButtonProps) {
  return (
    <button
      type="button"
      className={cn("inline-flex cursor-pointer items-center duration-[160ms] ease-bt pointer-coarse:min-h-11", VARIANTS[variant], className)}
      {...props}
    >
      {Icon && <Icon aria-hidden="true" size={variant === "primary" ? 14 : 12} strokeWidth={variant === "primary" ? 2.5 : 2} />}
      {children}
    </button>
  );
}
