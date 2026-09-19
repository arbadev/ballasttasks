"use client";

import { Calendar, ChevronLeft, ChevronRight, CircleAlert, Clock, ListChecks, Paperclip } from "lucide-react";
import { useId, useState, type DragEvent, type FocusEvent, type KeyboardEvent, type MouseEvent } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { cn } from "@/lib/cn";
import type { StatusDefinition } from "../model/statuses";
import type { Person, Task } from "../model/types";
import { entranceDelay, type CardView } from "./cardView";

interface TaskCardProps {
  task: Task;
  view: CardView;
  /** Position in the column, for the entrance stagger. */
  index: number;
  projectName: string;
  assignee: Person | null;
  assigneeIsCurrentUser: boolean;
  /**
   * The task open in the detail panel. The design gives it no look of its own (the panel
   * covers the board while it is open), so this only reaches assistive tech.
   */
  selected: boolean;
  dragging: boolean;
  /** The neighbouring statuses; null at either end of the workflow. */
  previous: StatusDefinition | null;
  next: StatusDefinition | null;
  onOpen(): void;
  onMove(to: StatusDefinition): void;
  onDragStart(event: DragEvent<HTMLElement>): void;
  onDragEnd(): void;
}

const RAIL = { danger: "bg-danger", warn: "bg-warn" };

const DUE_TONE = {
  danger: "bg-danger-soft font-medium text-danger",
  warn: "bg-warn-soft font-medium text-warn",
  quiet: "text-fg-3",
};

const PRIORITY_TONE = {
  // The design sets this mark in white, which is 3:1 on --danger; --acc-fg reads at 6:1.
  hot: "bg-danger text-acc-fg",
  p0: "bg-danger-soft text-danger",
  p1: "bg-acc-soft text-acc",
  p2: "bg-card-2 text-fg-2",
  p3: "bg-card-2 text-fg-3",
};

const DUE_MARK = { overdue: CircleAlert, soon: Clock, later: Calendar };

/** Focus that arrived by keyboard. An engine without `:focus-visible` counts every focus. */
function isKeyboardFocus(element: Element): boolean {
  try {
    return element.matches(":focus-visible");
  } catch {
    return true;
  }
}

const MOVE_BUTTON =
  "inline-flex h-[26px] cursor-pointer items-center gap-1 rounded-bt-sm bg-card-2 px-2 font-mono text-[10.5px] text-fg-2 transition-[color] duration-[160ms] ease-bt hover:text-fg pointer-coarse:h-9 pointer-coarse:px-3";

export function TaskCard({ task, view, index, projectName, assignee, assigneeIsCurrentUser, selected, dragging, previous, next, onOpen, onMove, onDragStart, onDragEnd }: TaskCardProps) {
  const titleId = useId();
  const hintId = useId();
  /**
   * Whether the keyboard has focus somewhere in the card. Held in state rather than read with
   * `:has(:focus-visible)`: while focus travels from one button to the next nothing matches,
   * and a row that hides for that instant takes the button about to be focused with it.
   */
  const [keyboardInside, setKeyboardInside] = useState(false);

  const onFocus = (event: FocusEvent<HTMLElement>) => {
    if (isKeyboardFocus(event.target)) setKeyboardInside(true);
  };
  const onBlur = (event: FocusEvent<HTMLElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget)) setKeyboardInside(false);
  };
  const DueMark = DUE_MARK[view.dueMark];

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!event.shiftKey) return;
    const target = event.key === "ArrowLeft" ? previous : event.key === "ArrowRight" ? next : null;
    if (!target) return;
    event.preventDefault();
    onMove(target);
  };

  /** A move button sits inside the card, whose click opens the task. */
  const moveTo = (target: StatusDefinition) => (event: MouseEvent) => {
    event.stopPropagation();
    onMove(target);
  };

  return (
    <article
      aria-labelledby={titleId}
      aria-current={selected ? "true" : undefined}
      data-dragging={dragging ? "true" : undefined}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      onFocus={onFocus}
      onBlur={onBlur}
      style={{ animationDelay: entranceDelay(index) }}
      className={cn(
        "relative flex animate-bt-in cursor-grab flex-col gap-2 overflow-hidden rounded-bt border border-line bg-card py-3 pr-3 pl-3.5 shadow-1",
        "transition-[translate,box-shadow,border-color,opacity] duration-[180ms] ease-bt hover:-translate-y-0.5 hover:border-line-2 hover:shadow-3",
        "outline-acc has-[[data-card-open]:focus-visible]:outline-2 has-[[data-card-open]:focus-visible]:outline-offset-2",
        dragging && "opacity-35",
      )}
    >
      <span aria-hidden="true" className={cn("absolute inset-y-0 left-0 w-[3px]", view.rail && RAIL[view.rail], view.blink && "animate-bt-blink")} />

      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] tracking-[.08em] text-fg-3 uppercase">{projectName}</span>
        <span className={cn("inline-flex h-[18px] items-center rounded-bt-sm px-1.5 font-mono text-[10px] tracking-[.04em]", PRIORITY_TONE[view.prioTone])}>
          <span className="sr-only">Priority </span>
          {view.prioLabel}
        </span>
      </div>

      <button
        type="button"
        id={titleId}
        data-card-open={task.id}
        aria-describedby={hintId}
        aria-keyshortcuts="Shift+ArrowLeft Shift+ArrowRight"
        onKeyDown={onKeyDown}
        className={cn(
          "cursor-[inherit] text-left text-[13.5px] leading-[1.35] font-medium tracking-[-0.005em] focus-visible:outline-none",
          view.done ? "text-fg-3 line-through" : "text-fg",
        )}
      >
        {task.title}
      </button>
      <span id={hintId} hidden>
        Press Enter to open. Hold Shift and the left or right arrow to move it to the previous or next status.
      </span>

      <div className="flex flex-wrap items-center gap-2.5 text-[11px] text-fg-3">
        <span className={cn("inline-flex h-[18px] items-center gap-1 rounded-bt-sm px-1.5 font-mono text-[10.5px]", DUE_TONE[view.dueTone ?? "quiet"])}>
          <DueMark aria-hidden="true" size={11} strokeWidth={view.dueMark === "later" ? 2 : 2.2} />
          {view.dueLabel}
        </span>
        {view.unassigned && (
          <span className="inline-flex h-[18px] items-center gap-1 rounded-bt-sm bg-info-soft px-1.5 font-mono text-[10.5px] font-medium text-info">needs owner</span>
        )}
        {view.stepsLabel && (
          <span title={`${view.stepsLabel.replace("/", " of ")} steps done`} className="inline-flex items-center gap-1 font-mono">
            <ListChecks aria-hidden="true" size={11} />
            {view.stepsLabel}
          </span>
        )}
        {view.attachmentsLabel && (
          <span title={`${view.attachmentsLabel} attachment${view.attachmentsLabel === "1" ? "" : "s"}`} className="inline-flex items-center gap-1 font-mono">
            <Paperclip aria-hidden="true" size={11} />
            {view.attachmentsLabel}
          </span>
        )}
        {assignee && (
          <span className="ml-auto flex">
            <Avatar initials={assignee.initials} name={assignee.name} tone={assigneeIsCurrentUser ? "accent" : "neutral"} size={22} />
          </span>
        )}
        {view.unassigned && (
          <span
            role="img"
            aria-label="Needs an owner"
            title="Needs an owner"
            className="ml-auto grid size-[22px] place-items-center rounded-bt-av border-[1.5px] border-dashed border-info font-mono text-[10px] text-info"
          >
            ?
          </span>
        )}
      </div>

      {/*
        Not in the design, which can only be dragged: the same move for keyboards (shown while
        the card has keyboard focus) and for touch screens (always shown on a coarse pointer).
      */}
      <div data-move-controls={keyboardInside ? "shown" : undefined} className={cn("items-center gap-1.5 border-t border-line pt-2", keyboardInside ? "flex" : "hidden pointer-coarse:flex")}>
        {previous && (
          <button type="button" aria-label={`Move "${task.title}" to ${previous.name}`} onClick={moveTo(previous)} className={MOVE_BUTTON}>
            <ChevronLeft aria-hidden="true" size={12} />
            {previous.name}
          </button>
        )}
        {next && (
          <button type="button" aria-label={`Move "${task.title}" to ${next.name}`} onClick={moveTo(next)} className={cn(MOVE_BUTTON, "ml-auto")}>
            {next.name}
            <ChevronRight aria-hidden="true" size={12} />
          </button>
        )}
      </div>
    </article>
  );
}
