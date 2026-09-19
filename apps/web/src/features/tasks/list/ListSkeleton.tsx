import { cn } from "@/lib/cn";

/** Title and meta widths, varied so the placeholder reads as a list rather than a table. */
const ROWS = [
  { title: "w-[46%]", meta: "w-[28%]" },
  { title: "w-[31%]", meta: "w-[34%]" },
  { title: "w-[52%]", meta: "w-[24%]" },
  { title: "w-[38%]", meta: "w-[30%]" },
  { title: "w-[44%]", meta: "w-[22%]" },
  { title: "w-[27%]", meta: "w-[32%]" },
];

const SHIMMER = "animate-bt-shimmer rounded-bt-sm bg-[linear-gradient(90deg,var(--card)_25%,var(--card-2)_50%,var(--card)_75%)] bg-[length:200%_100%]";

/** The list while the tasks load: the quick-add line and six rows in the real rows' geometry. */
export function ListSkeleton() {
  return (
    <div role="status" className="flex flex-col">
      <span className="sr-only">Loading tasks…</span>
      <div aria-hidden="true" className="flex items-center gap-[14px] border-b border-line px-6 py-[9px] max-md:gap-3 max-md:px-4">
        <span className="size-[18px] flex-none rounded-bt-sm border-[1.5px] border-dashed border-line-2" />
        <span className={cn(SHIMMER, "my-[10.5px] h-3 w-44")} />
      </div>
      {ROWS.map((row, i) => (
        <div
          key={i}
          data-testid="skeleton-row"
          aria-hidden="true"
          className="grid grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-[14px] border-b border-line px-6 py-[11px] max-md:gap-x-3 max-md:px-4"
        >
          <span className="size-[18px] rounded-bt-sm border-[1.5px] border-line" />
          <span className="flex min-w-0 flex-col gap-1">
            <span className={cn(SHIMMER, "my-[3px] h-3", row.title)} />
            <span className={cn(SHIMMER, "my-[5px] h-2.5", row.meta)} />
          </span>
          <span className="flex items-center gap-[14px] max-sm:hidden">
            <span className={cn(SHIMMER, "h-3 w-10")} />
            <span className={cn(SHIMMER, "h-5 w-[30px]")} />
            <span className={cn(SHIMMER, "size-[26px] rounded-bt-av")} />
          </span>
        </div>
      ))}
    </div>
  );
}
