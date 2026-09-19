import type { LucideIcon } from "lucide-react";
import type { CSSProperties } from "react";
import { cn } from "@/lib/cn";

interface SegmentedControlProps<T extends string> {
  /** Accessible name of the radio group. */
  label: string;
  /** Radio group name; must be unique on the page. */
  name: string;
  value: T;
  options: readonly { value: T; label: string; icon?: LucideIcon }[];
  onChange: (value: T) => void;
}

/** Native radios (so arrow keys work) under a sliding thumb. */
export function SegmentedControl<T extends string>({ label, name, value, options, onChange }: SegmentedControlProps<T>) {
  const index = Math.max(0, options.findIndex((o) => o.value === value));
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="relative grid h-[34px] rounded-r border border-line bg-card p-[3px]"
      style={{ gridTemplateColumns: `repeat(${options.length}, 1fr)` }}
    >
      <span
        aria-hidden="true"
        data-thumb
        // Positioned with `left`, as the design does, not a transform: layout snaps to the pixel
        // grid, while a transform leaves a blurred edge when a segment is a fractional width.
        className="absolute top-[3px] bottom-[3px] left-[calc(3px+var(--segment)*(100%-6px)/var(--segments))] w-[calc((100%-6px)/var(--segments))] rounded-[calc(var(--r)-3px)] bg-card-2 shadow-1 transition-[left] duration-[280ms] ease-bt"
        style={{ "--segment": index, "--segments": options.length } as CSSProperties}
      />
      {options.map(({ value: v, label: text, icon: Icon }) => (
        <label
          key={v}
          className={cn(
            // The radio itself is invisible, so the label carries its focus ring.
            "relative flex cursor-pointer items-center justify-center gap-1.5 rounded-[calc(var(--r)-3px)] px-3 text-[12.5px] font-medium transition-colors duration-200 ease-bt has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-acc",
            v === value ? "text-fg" : "text-fg-2",
          )}
        >
          <input type="radio" name={name} value={v} checked={v === value} onChange={() => onChange(v)} className="absolute size-0 opacity-0" />
          {Icon && <Icon aria-hidden="true" size={13} strokeWidth={2} />}
          {text}
        </label>
      ))}
    </div>
  );
}
