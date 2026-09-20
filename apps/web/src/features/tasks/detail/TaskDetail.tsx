"use client";

import { useCallback, useEffect, useRef, type KeyboardEvent } from "react";
import type { Task } from "../model/types";
import { useWorkspace } from "../workspace/WorkspaceProvider";
import { ActivitySection } from "./ActivitySection";
import { AttachmentsSection } from "./AttachmentsSection";
import { DetailFooter } from "./DetailFooter";
import { DetailHeader } from "./DetailHeader";
import { DetailSessionProvider } from "./DetailSession";
import { PropertiesPanel } from "./PropertiesPanel";
import { StepsSection } from "./StepsSection";
import { DescriptionField, TitleField } from "./TextFields";
import { UrgencyBanner } from "./UrgencyBanner";
import { useStepGeneration } from "./useStepGeneration";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Not `display: none`: the back and close controls swap with the breakpoint, and only one can take focus. */
const isShown = (el: HTMLElement) => getComputedStyle(el).display !== "none";

const focusableIn = (panel: HTMLElement) => [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(isShown);

/**
 * The task side panel. The shell keeps this mounted, so the session around the dialog (saves
 * in flight, unsent drafts, failed generations) outlives any one task being open.
 */
export function TaskDetail() {
  const { state, actions } = useWorkspace();
  const task = state.tasks.find((t) => t.id === state.selectedId) ?? null;

  // Ids seen before this render. A selected task that is not among them was created just now.
  const seenIds = useRef<ReadonlySet<string>>(new Set());
  const wasSeen = useCallback((id: string) => seenIds.current.has(id), []);
  useEffect(() => {
    seenIds.current = new Set(state.tasks.map((t) => t.id));
  }, [state.tasks]);

  return <DetailSessionProvider>{task && <DetailDialog task={task} wasSeen={wasSeen} onClose={actions.clearSelection} />}</DetailSessionProvider>;
}

interface DetailDialogProps {
  task: Task;
  /** Asked once per task, from an effect that runs before TaskDetail records the new ids. */
  wasSeen: (id: string) => boolean;
  onClose: () => void;
}

function DetailDialog({ task, wasSeen, onClose }: DetailDialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const fresh = useRef<{ id: string; isNew: boolean } | null>(null);

  // Remember what opened the panel, and hand focus back to it on the way out.
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      if (opener?.isConnected) opener.focus();
    };
  }, []);

  // Focus moves into the panel: onto the selected title of a task created just now, so typing
  // names it; otherwise onto the panel itself, so reading starts at the top.
  useEffect(() => {
    if (fresh.current?.id !== task.id) fresh.current = { id: task.id, isNew: !wasSeen(task.id) };
    if (fresh.current.isNew) {
      titleRef.current?.focus();
      titleRef.current?.select();
    } else {
      panelRef.current?.focus();
    }
  }, [task.id, wasSeen]);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      // A control inside the panel (the link form, the delete prompt) may have used Escape itself.
      if (e.key === "Escape" && !e.defaultPrevented) return onClose();
      // A control that disables or unmounts itself under the reader (a send button once its box
      // is busy, a step's own Remove) leaves the focus on the document. `keepTabInside` never
      // sees a key pressed out there, so the open dialog takes this one back.
      if (e.key !== "Tab" || e.defaultPrevented || !panelRef.current) return;
      const active = document.activeElement;
      if (active && active !== document.body && active !== document.documentElement) return;
      e.preventDefault();
      const stops = focusableIn(panelRef.current);
      ((e.shiftKey ? stops[stops.length - 1] : stops[0]) ?? panelRef.current).focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const keepTabInside = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab" || !panelRef.current) return;
    const focusable = focusableIn(panelRef.current);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === panelRef.current)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    <div data-testid="detail-backdrop" onClick={onClose} className="fixed inset-0 z-50 flex animate-bt-fade justify-end bg-backdrop backdrop-blur-[6px]">
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={task.title || "Untitled task"}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={keepTabInside}
        className="flex h-full w-[min(920px,100%)] max-w-full animate-bt-panel flex-col overflow-hidden border-l border-line bg-panel shadow-2 focus-visible:outline-none max-md:border-l-0"
      >
        {/* Keyed by task: every field's edit state belongs to one task and is flushed when it goes. */}
        <DetailBody key={task.id} task={task} titleRef={titleRef} onClose={onClose} />
      </div>
    </div>
  );
}

function DetailBody({ task, titleRef, onClose }: { task: Task; titleRef: React.Ref<HTMLInputElement>; onClose: () => void }) {
  const generation = useStepGeneration(task.id);

  return (
    <>
      <DetailHeader task={task} onClose={onClose} />
      <UrgencyBanner task={task} generation={generation} />
      <div className="flex min-h-0 flex-1 flex-wrap content-start overflow-x-hidden overflow-y-auto">
        <div className="flex min-w-0 flex-[1_1_440px] flex-col gap-[22px] px-6 pt-[22px] pb-8 max-md:px-4">
          <TitleField task={task} inputRef={titleRef} />
          <DescriptionField task={task} />
          <StepsSection task={task} generation={generation} />
          <AttachmentsSection task={task} />
          <ActivitySection task={task} />
        </div>
        <PropertiesPanel task={task} />
      </div>
      <DetailFooter task={task} />
    </>
  );
}
