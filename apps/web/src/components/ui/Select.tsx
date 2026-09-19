import { ChevronDown } from "lucide-react";
import { useId } from "react";
import { cn } from "@/lib/cn";

interface SelectProps<T extends string> {
  /** Visible prefix inside the control, and the select's accessible name. */
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
  className?: string;
}

/** A native select dressed as the design's inline "Label Value ⌄" control. */
export function Select<T extends string>({ label, value, options, onChange, className }: SelectProps<T>) {
  // Chrome flags a form field with neither an id nor a name; the wrapping label still names it.
  const id = useId();
  return (
    <label
      className={cn(
        "relative flex h-[30px] items-center rounded-bt border border-line bg-card pl-2.5 text-[12.5px] text-fg-3 transition-colors duration-[160ms] ease-bt hover:border-line-2 pointer-coarse:h-11",
        className,
      )}
    >
      {label}
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        className="h-7 cursor-pointer appearance-none border-0 bg-transparent py-0 pr-[26px] pl-1.5 text-[12.5px] font-medium text-fg"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown aria-hidden="true" size={12} strokeWidth={2} className="pointer-events-none absolute right-2" />
    </label>
  );
}
