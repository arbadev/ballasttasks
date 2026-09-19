"use client";

import { Plus } from "lucide-react";
import { useId, type DragEvent, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { StatusDefinition } from "../model/statuses";

interface BoardColumnProps {
  status: StatusDefinition;
  count: number;
  /** A card is being dragged over this column. */
  dropTarget: boolean;
  onDragOver(event: DragEvent<HTMLElement>): void;
  onDrop(event: DragEvent<HTMLElement>): void;
  onAddTask(): void;
  /** The cards, one `<li>` each. */
  children: ReactNode;
}

const DOT = { muted: "bg-fg-3", accent: "bg-acc", warn: "bg-warn", ok: "bg-ok" };

export function BoardColumn({ status, count, dropTarget, onDragOver, onDrop, onAddTask, children }: BoardColumnProps) {
  const headingId = useId();

  return (
    <section
      aria-labelledby={headingId}
      data-column={status.id}
      data-drop-target={dropTarget ? "true" : undefined}
      onDragOver={onDragOver}
      onDrop={onDrop}
      className={cn(
        "-m-2 flex min-h-[360px] snap-start flex-col gap-2.5 rounded-bt p-2 outline-1 -outline-offset-1 outline-dashed",
        "transition-[background-color,outline-color] duration-200 ease-bt",
        dropTarget ? "bg-acc-soft outline-acc" : "outline-transparent",
      )}
    >
      <div className="flex items-center gap-2 border-b border-line px-1 pt-1 pb-2.5">
        <span aria-hidden="true" className={cn("size-2 flex-none rounded-full", DOT[status.tone])} />
        {/* Focusable only from code: where focus lands when a move takes the last card out of the column. */}
        <h2
          id={headingId}
          data-column-heading=""
          tabIndex={-1}
          className="m-0 rounded-bt-sm text-[13px] font-semibold focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-acc"
        >
          {status.name}
        </h2>
        <span data-testid="column-count" className="ml-auto font-mono text-[11px] text-fg-3">
          {count}
          <span className="sr-only">{count === 1 ? " task" : " tasks"}</span>
        </span>
      </div>

      {count > 0 ? (
        <ul className="m-0 flex list-none flex-col gap-2.5 p-0">{children}</ul>
      ) : (
        <p className="m-0 rounded-bt border border-dashed border-line-2 px-3 py-[26px] text-[12px] text-fg-3">Drop tasks here</p>
      )}

      <button
        type="button"
        onClick={onAddTask}
        className="inline-flex h-[30px] cursor-pointer items-center gap-1.5 self-start rounded-bt-sm px-2 text-[12.5px] text-fg-3 transition-colors duration-[160ms] ease-bt hover:bg-card hover:text-fg"
      >
        <Plus aria-hidden="true" size={13} />
        Add a task
      </button>
    </section>
  );
}
