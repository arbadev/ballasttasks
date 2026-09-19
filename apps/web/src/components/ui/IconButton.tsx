import type { LucideIcon } from "lucide-react";
import type { Ref } from "react";
import Link from "next/link";
import { cn } from "@/lib/cn";

interface IconButtonProps {
  icon: LucideIcon;
  /** The accessible name; also the tooltip, unless `title` gives the tooltip shorter words. */
  label: string;
  /** The tooltip, when the accessible name says more than the design shows. Defaults to `label`. */
  title?: string;
  /** Renders a link instead of a button. */
  href?: string;
  onClick?: () => void;
  /** The button element, for a caller that returns focus to it. Not used by the link form. */
  buttonRef?: Ref<HTMLButtonElement>;
  className?: string;
  "aria-expanded"?: boolean;
  "aria-controls"?: string;
  "aria-haspopup"?: "dialog" | "menu";
}

const BASE =
  "inline-grid size-7 flex-none cursor-pointer place-items-center rounded-bt-sm text-fg-3 transition-colors duration-[160ms] ease-bt hover:bg-card-2 hover:text-fg pointer-coarse:size-11";

export function IconButton({ icon: Icon, label, title = label, href, onClick, buttonRef, className, ...aria }: IconButtonProps) {
  const icon = <Icon aria-hidden="true" size={15} strokeWidth={2} />;
  if (href) {
    return (
      <Link href={href} aria-label={label} title={title} className={cn(BASE, className)}>
        {icon}
      </Link>
    );
  }
  return (
    <button ref={buttonRef} type="button" aria-label={label} title={title} onClick={onClick} className={cn(BASE, className)} {...aria}>
      {icon}
    </button>
  );
}
