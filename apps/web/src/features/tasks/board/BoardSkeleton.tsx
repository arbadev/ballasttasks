import { cn } from "@/lib/cn";
import { BOARD_GRID } from "./layout";

/** How many placeholder cards each column gets: uneven on purpose, like a real board. */
const CARDS_PER_COLUMN = [3, 2, 2, 1];

/** The design's shimmer (its generated-steps placeholder), reused at the board's shapes. */
const SHIMMER = "block animate-bt-shimmer rounded-bt bg-[linear-gradient(90deg,var(--card-2)_25%,var(--line-2)_50%,var(--card-2)_75%)] bg-[length:200%_100%]";

export function BoardSkeleton() {
  return (
    <div role="status" aria-label="Loading the board" className={BOARD_GRID}>
      {CARDS_PER_COLUMN.map((cards, column) => (
        <div key={column} data-testid="skeleton-column" aria-hidden="true" className="flex flex-col gap-2.5">
          <div className="flex items-center gap-2 border-b border-line px-1 pt-1 pb-2.5">
            <span className="size-2 flex-none rounded-full bg-card-2" />
            <span className={cn(SHIMMER, "h-[10px] w-20")} />
          </div>
          {Array.from({ length: cards }, (_, card) => (
            <div key={card} className="flex flex-col gap-3 rounded-bt border border-line bg-card py-3 pr-3 pl-3.5 shadow-1">
              <span className={cn(SHIMMER, "h-2 w-1/3")} />
              <span className={cn(SHIMMER, "h-[10px]", card % 2 ? "w-3/5" : "w-4/5")} />
              <span className={cn(SHIMMER, "h-2 w-2/5")} />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
