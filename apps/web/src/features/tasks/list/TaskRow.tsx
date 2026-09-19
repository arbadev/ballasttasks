import { Calendar, Check, CircleAlert, Clock, ListChecks, Paperclip, User } from "lucide-react";
import type { KeyboardEvent } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { cn } from "@/lib/cn";
import type { Person, Task } from "../model/types";
import type { DueIcon, DueTone, PriorityTone, Rail, RowView } from "./rowView";

/** Where the arrow keys, Home and End send focus. */
export type RowMove = "previous" | "next" | "first" | "last";

interface TaskRowProps {
  task: Task;
  view: RowView;
  projectName: string;
  assignee: Person | null;
  assigneeIsCurrentUser: boolean;
  selected: boolean;
  onOpen: () => void;
  onToggle: () => void;
  onMove: (move: RowMove) => void;
}

const DUE_TONES: Record<DueTone, string> = {
  danger: "bg-danger-soft font-medium text-danger",
  warn: "bg-warn-soft font-medium text-warn",
  later: "bg-transparent font-normal text-fg-3",
};

const DUE_ICONS: Record<DueIcon, { icon: typeof Clock; strokeWidth: number }> = {
  overdue: { icon: CircleAlert, strokeWidth: 2.2 },
  soon: { icon: Clock, strokeWidth: 2.2 },
  later: { icon: Calendar, strokeWidth: 2 },
};

const RAILS: Record<Rail, string> = { danger: "bg-danger", warn: "bg-warn", none: "bg-transparent" };

const PRIORITY_TONES: Record<PriorityTone, string> = {
  // Dark text on the solid pill: the design's white on --danger measures 3.01:1 (fails AA), --acc-fg 6.13:1.
  hot: "bg-danger text-acc-fg",
  danger: "bg-danger-soft text-danger",
  accent: "bg-acc-soft text-acc",
  neutral: "bg-card-2 text-fg-2",
  muted: "bg-card-2 text-fg-3",
};

const MOVES: Record<string, RowMove> = { ArrowUp: "previous", ArrowDown: "next", Home: "first", End: "last" };

const CHIP = "inline-flex h-5 items-center gap-[5px] rounded-bt-sm px-[7px] font-mono text-[11px]";
const COUNT = "inline-flex items-center gap-1 font-mono text-[11px]";

/**
 * One task in the list. The title is the row's button (Enter opens, Space completes, the
 * arrows move between rows) and the whole row is its pointer target; the checkbox completes
 * without opening.
 */
export function TaskRow({ task, view, projectName, assignee, assigneeIsCurrentUser, selected, onOpen, onToggle, onMove }: TaskRowProps) {
  const DueIconGlyph = DUE_ICONS[view.dueIcon];

  const onTitleKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      onOpen();
    } else if (e.key === " ") {
      e.preventDefault();
      onToggle();
    }
  };

  const onRowKey = (e: KeyboardEvent<HTMLLIElement>) => {
    const move = MOVES[e.key];
    if (!move) return;
    e.preventDefault();
    onMove(move);
  };

  return (
    <li
      data-task-id={task.id}
      aria-current={selected ? "true" : undefined}
      onClick={onOpen}
      onKeyDown={onRowKey}
      style={{ animationDelay: `${view.delayMs}ms` }}
      className={cn(
        "relative grid animate-bt-in cursor-pointer grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-[14px] border-b border-line px-6 py-[11px] transition-[background-color] duration-[160ms] ease-bt",
        "has-[[data-row-title]:focus-visible]:outline-2 has-[[data-row-title]:focus-visible]:-outline-offset-2 has-[[data-row-title]:focus-visible]:outline-acc",
        "max-md:grid-cols-[18px_minmax(0,1fr)] max-md:items-start max-md:gap-x-3 max-md:gap-y-2 max-md:px-4",
        selected ? "bg-acc-soft" : "bg-transparent hover:bg-card",
      )}
    >
      <span data-testid="rail" aria-hidden="true" className={cn("absolute inset-y-0 left-0 w-[3px]", RAILS[view.rail], view.blink && "animate-bt-blink")} />

      <button
        type="button"
        role="checkbox"
        aria-checked={view.done}
        aria-label={`Complete: ${task.title}`}
        onClick={(e) => {
          e.stopPropagation();
          onToggle();
        }}
        className={cn(
          "relative grid size-[18px] cursor-pointer place-items-center rounded-bt-sm border-[1.5px] p-0 text-acc-fg transition-[border-color,background-color,transform] duration-[160ms] ease-bt hover:scale-[1.08] hover:border-acc",
          // The visible box stays 18px; the pointer target around it is 36px, 44px for touch.
          "before:absolute before:-inset-[9px] before:content-[''] pointer-coarse:before:-inset-[13px] max-md:mt-px",
          view.done ? "border-acc bg-acc" : "border-line-2 bg-transparent",
        )}
      >
        {view.done && <Check data-testid="check" aria-hidden="true" size={12} strokeWidth={3} className="animate-bt-pop" />}
      </button>

      <div className="flex min-w-0 flex-col gap-1">
        <button
          type="button"
          data-row-title=""
          onKeyDown={onTitleKey}
          className={cn(
            "block w-full cursor-pointer truncate bg-transparent p-0 text-left text-sm leading-[1.3] font-medium tracking-[-0.005em] outline-none transition-[color] duration-200 ease-bt",
            "max-md:line-clamp-2 max-md:whitespace-normal",
            view.done ? "text-fg-3 line-through" : "text-fg",
          )}
        >
          {task.title}
        </button>

        {/* Sizes are arbitrary values on purpose: text-xs / text-sm would also set their own line
            height, and the design's meta line inherits 1.5 (18px, 15px and 16.5px per size). */}
        <div className="flex flex-wrap items-center gap-3 text-[12px] text-fg-3 max-md:gap-x-2.5 max-md:gap-y-1">
          <span className="font-mono text-[10px] tracking-[.08em] uppercase">{projectName}</span>
          <span data-testid="due" data-tone={view.dueTone} className={cn(CHIP, "transition-[background-color,color] duration-200 ease-bt", DUE_TONES[view.dueTone])}>
            <DueIconGlyph.icon aria-hidden="true" size={12} strokeWidth={DueIconGlyph.strokeWidth} />
            {view.dueLabel}
          </span>
          {view.needsOwner && (
            <span className={cn(CHIP, "bg-info-soft font-medium text-info")}>
              <User aria-hidden="true" size={12} strokeWidth={2.2} />
              needs owner
            </span>
          )}
          {view.stepsLabel && (
            <span className={COUNT}>
              <ListChecks aria-hidden="true" size={12} strokeWidth={2} />
              <span className="sr-only">Steps done </span>
              {view.stepsLabel}
            </span>
          )}
          {view.attachmentCount > 0 && (
            <span className={COUNT}>
              <Paperclip aria-hidden="true" size={12} strokeWidth={2} />
              <span className="sr-only">Attachments </span>
              <span data-testid="attachment-count">{view.attachmentCount}</span>
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-[14px] max-md:col-start-2 max-md:justify-self-start">
        <div title="Importance" className="flex w-10 flex-col items-end gap-1 max-md:w-auto max-md:flex-row max-md:items-center max-md:gap-2">
          <span className="sr-only">Importance </span>
          <span className="font-mono text-xs leading-none text-fg-2 tabular-nums">{view.importance}</span>
          <span aria-hidden="true" className="block h-[3px] w-9 overflow-hidden rounded-bt-sm bg-line-2">
            <span style={{ width: `${view.importance}%` }} className={cn("block h-full rounded-bt-sm transition-[width] duration-[400ms] ease-bt", view.importanceAccent ? "bg-acc" : "bg-fg-2")} />
          </span>
        </div>
        <span className={cn("inline-flex h-5 items-center rounded-bt-sm px-[7px] font-mono text-[10.5px] tracking-[.04em]", PRIORITY_TONES[view.prioTone])}>
          <span className="sr-only">Priority </span>
          {view.prioLabel}
        </span>
        {assignee && <Avatar initials={assignee.initials} name={assignee.name} tone={assigneeIsCurrentUser ? "accent" : "neutral"} size={26} />}
        {view.needsOwner && (
          <span role="img" aria-label="Needs an owner" title="Needs an owner" className="grid size-[26px] flex-none place-items-center rounded-bt-av border-[1.5px] border-dashed border-info font-mono text-[11px] text-info">
            ?
          </span>
        )}
      </div>
    </li>
  );
}
