import type { ReactNode, Ref } from "react";
import { cn } from "@/lib/cn";

interface FieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  invalid?: boolean;
  /** Ids of the FieldMessages that describe this input. */
  describedBy?: string;
  disabled?: boolean;
  maxLength?: number;
  /** Codes and keys are set in the monospace face, as the design sets dates and numbers. */
  mono?: boolean;
  /** The dialog puts the focus here when it opens. */
  autoFocus?: boolean;
  inputRef?: Ref<HTMLInputElement>;
  className?: string;
}

/** The design's form field: a quiet label above a 34px input. */
export function Field({ id, label, value, onChange, invalid = false, describedBy, disabled, maxLength, mono, autoFocus, inputRef, className }: FieldProps) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-[11.5px] text-fg-3">
        {label}
      </label>
      <input
        ref={inputRef}
        id={id}
        name={label.toLowerCase()}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        maxLength={maxLength}
        autoComplete="off"
        spellCheck={false}
        data-autofocus={autoFocus || undefined}
        aria-invalid={invalid}
        aria-describedby={describedBy}
        className={cn(
          "h-[34px] w-full rounded-bt border bg-card px-2.5 text-[13px] text-fg transition-[border-color,box-shadow] duration-[160ms] ease-bt disabled:cursor-not-allowed disabled:opacity-50 pointer-coarse:h-11",
          mono && "font-mono tracking-[.04em]",
          invalid ? "border-danger focus:shadow-[0_0_0_3px_var(--danger-soft)] focus-visible:outline-danger" : "border-line focus:border-acc focus:shadow-[0_0_0_3px_var(--acc-soft)]",
        )}
      />
    </div>
  );
}

/** The line under a field: a hint in the quiet tone, or what is wrong in the danger tone. */
export function FieldMessage({ id, tone = "hint", children }: { id: string; tone?: "hint" | "error"; children: ReactNode }) {
  return (
    <p id={id} className={cn("m-0 leading-[1.45]", tone === "error" ? "animate-bt-in text-[12px] text-danger" : "text-[11.5px] text-fg-3")}>
      {children}
    </p>
  );
}
