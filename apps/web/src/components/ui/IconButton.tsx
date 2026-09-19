import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/cn";

interface IconButtonProps {
  icon: LucideIcon;
  /** The accessible name; also shown as a tooltip. */
  label: string;
  /** Renders a link instead of a button. */
  href?: string;
  onClick?: () => void;
  className?: string;
  "aria-expanded"?: boolean;
  "aria-controls"?: string;
}

const BASE =
  "inline-grid size-7 flex-none cursor-pointer place-items-center rounded-bt-sm text-fg-3 transition-colors duration-[160ms] ease-bt hover:bg-card-2 hover:text-fg pointer-coarse:size-11";

export function IconButton({ icon: Icon, label, href, onClick, className, ...aria }: IconButtonProps) {
  const icon = <Icon aria-hidden="true" size={15} strokeWidth={2} />;
  if (href) {
    return (
      <Link href={href} aria-label={label} title={label} className={cn(BASE, className)}>
        {icon}
      </Link>
    );
  }
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} className={cn(BASE, className)} {...aria}>
      {icon}
    </button>
  );
}
