import { ChevronDown, type LucideIcon } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/cn";

/** The panel's section headings: "STEPS", "ATTACHMENTS", "ACTIVITY". */
export const SECTION_LABEL = "m-0 font-mono text-[10.5px] font-normal tracking-[.1em] text-fg-3 uppercase";

/** Boxed inputs of the panel: comment box, link form, due date, importance. */
export const BOX_INPUT =
  "w-full rounded-bt border border-line bg-card text-fg transition-[border-color,box-shadow] duration-[160ms] ease-bt placeholder:text-fg-3 placeholder:opacity-100 focus:border-acc focus:shadow-[0_0_0_3px_var(--acc-soft)]";

/** Grows the touch target of a small control without moving a pixel of it. */
export const HIT_AREA = "relative after:absolute after:-inset-2.5 after:content-['']";

const VARIANTS = {
  /** The accent action inside the panel: Generate steps, Add n steps. */
  accent:
    "h-8 gap-2 rounded-bt bg-acc px-3 text-[12.5px] font-semibold text-acc-fg shadow-glow transition-[transform,filter] hover:-translate-y-px hover:brightness-[1.08] active:translate-y-0 active:scale-[.98]",
  /** Bordered and neutral: Attach file, Add link, Regenerate, Comment. The caller sets height and padding. */
  secondary: "gap-[7px] rounded-bt border border-line-2 bg-card text-[12.5px] font-medium text-fg transition-colors hover:border-fg-3 hover:bg-card-2",
  /** Text only: Discard, Cancel, Keep. The caller sets the height. */
  quiet: "gap-1.5 rounded-bt-sm bg-transparent px-2.5 text-[12.5px] text-fg-3 transition-colors hover:bg-card hover:text-fg",
  /** Text only, turning red: Delete. */
  danger: "h-[34px] rounded-bt-sm bg-transparent px-2.5 text-[13px] text-fg-3 transition-colors hover:bg-danger-soft hover:text-danger",
  /** The committing click: Delete's second press, and "Clear date" on the emptied due date. */
  confirm: "h-[34px] rounded-bt-sm bg-danger-soft px-2.5 text-[13px] font-medium text-danger transition-[filter] hover:brightness-125",
  /** Sits on the attention banner and takes its colour. */
  banner: "h-7 gap-1.5 rounded-bt border border-current/35 bg-current/10 px-2.5 text-[12.5px] font-medium text-inherit transition-colors hover:bg-current/20",
};

interface PanelButtonProps extends ComponentProps<"button"> {
  variant: keyof typeof VARIANTS;
  icon?: LucideIcon;
  iconSize?: number;
  iconStroke?: number;
}

/** The panel's own button sizes, which the shell's Button does not have. */
export function PanelButton({ variant, icon: Icon, iconSize = 13, iconStroke = 2, className, children, ...props }: PanelButtonProps) {
  return (
    <button
      type="button"
      className={cn("inline-flex flex-none cursor-pointer items-center duration-[160ms] ease-bt pointer-coarse:min-h-11", VARIANTS[variant], className)}
      {...props}
    >
      {Icon && <Icon aria-hidden="true" size={iconSize} strokeWidth={iconStroke} />}
      {children}
    </button>
  );
}

interface PropertySelectProps {
  id: string;
  name: string;
  value: string;
  options: readonly { value: string; label: string }[];
  onChange: (value: string) => void;
  mono?: boolean;
}

/** A native select in the panel's full-width dress. Its label is rendered by the caller. */
export function PropertySelect({ id, name, value, options, onChange, mono }: PropertySelectProps) {
  return (
    <div className="relative flex items-center">
      <select
        id={id}
        name={name}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "h-[34px] w-full cursor-pointer appearance-none rounded-bt border border-line bg-card pr-[30px] pl-2.5 text-[13px] text-fg transition-colors duration-[160ms] ease-bt hover:border-line-2 pointer-coarse:h-11",
          mono && "font-mono",
        )}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown aria-hidden="true" size={13} strokeWidth={2} className="pointer-events-none absolute right-2.5 text-fg-3" />
    </div>
  );
}

const ERROR_ACTION = "cursor-pointer rounded-bt-sm border-0 bg-transparent p-0 text-[12px] font-medium text-danger underline underline-offset-2 hover:text-fg";

/**
 * The inline message under something that failed: what happened, and a way to try it again.
 * `onDismiss` is for a failure that is held until it is dealt with, such as an unsent step.
 */
export function ActionError({ children, onRetry, onDismiss, retryLabel = "Retry" }: { children: ReactNode; onRetry: () => void; onDismiss?: () => void; retryLabel?: string }) {
  return (
    <p role="alert" className="m-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-danger">
      <span>{children}</span>
      <button type="button" onClick={onRetry} className={ERROR_ACTION}>
        {retryLabel}
      </button>
      {onDismiss && (
        <button type="button" onClick={onDismiss} className={ERROR_ACTION}>
          Dismiss
        </button>
      )}
    </p>
  );
}

/** The inline message under a field whose save failed: what happened, and a way forward. */
export function SaveError({ what, onRetry }: { what: string; onRetry: () => void }) {
  return <ActionError onRetry={onRetry}>Could not save the {what}.</ActionError>;
}

export function FieldLabel({ htmlFor, children }: { htmlFor: string; children: ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="text-[11.5px] text-fg-3">
      {children}
    </label>
  );
}
