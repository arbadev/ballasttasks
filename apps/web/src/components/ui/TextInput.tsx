import type { LucideIcon } from "lucide-react";
import { useId } from "react";
import { cn } from "@/lib/cn";

interface TextInputProps {
  /** Accessible name; the design shows no visible label for its search box. */
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "search";
  placeholder?: string;
  maxLength?: number;
  icon?: LucideIcon;
  className?: string;
}

export function TextInput({ label, value, onChange, type = "text", placeholder, maxLength, icon: Icon, className }: TextInputProps) {
  // Chrome flags a form field with neither an id nor a name.
  const id = useId();
  return (
    <div className={cn("relative flex items-center", className)}>
      {Icon && <Icon aria-hidden="true" size={13} strokeWidth={2} className="pointer-events-none absolute left-2.5 text-fg-3" />}
      <input
        id={id}
        type={type}
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        maxLength={maxLength}
        className={cn(
          "h-[30px] w-full appearance-none rounded-bt border border-line bg-card pr-2.5 text-[12.5px] text-fg placeholder:text-fg-3 placeholder:opacity-100 transition-[border-color,box-shadow] duration-[160ms] ease-bt focus:border-acc focus:shadow-[0_0_0_3px_var(--acc-soft)] pointer-coarse:h-11 [&::-webkit-search-cancel-button]:appearance-none",
          Icon ? "pl-[30px]" : "pl-2.5",
        )}
      />
    </div>
  );
}
