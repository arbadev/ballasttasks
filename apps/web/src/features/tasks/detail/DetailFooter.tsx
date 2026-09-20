"use client";

import { Check } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { relativeTime } from "../model/time";
import type { Task } from "../model/types";
import { useNow, useTaskCommands } from "../workspace/WorkspaceProvider";
import { PanelButton } from "./controls";
import { useDetailSession, type SaveStatus } from "./DetailSession";

const SAVE_TEXT: Record<Exclude<SaveStatus, "idle">, string> = { saving: "saving…", refreshing: "reloading…", refresh: "saved · reload needed", failed: "not saved" };

/** Complete or reopen, delete (asked twice, there is no undo), and the autosave indicator. */
export function DetailFooter({ task }: { task: Task }) {
  const now = useNow();
  const commands = useTaskCommands();
  const { track, saveStatus } = useDetailSession();
  const [confirming, setConfirming] = useState(false);
  const [deleteFailed, setDeleteFailed] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const deleteRef = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(false);
  const status = saveStatus(task.id);

  const remove = () =>
    void track(task.id, commands.remove(task.id)).catch(() => {
      setConfirming(false);
      setDeleteFailed(true);
    });

  const closePrompt = () => {
    setConfirming(false);
    setDeleteFailed(false);
  };

  // The prompt owns the focus for as long as it is up, and hands it back to the Delete button
  // it came from; without that, closing it would drop the focus out of the modal onto <body>.
  useEffect(() => {
    if (confirming) {
      wasConfirming.current = true;
      confirmRef.current?.focus();
      return;
    }
    if (!wasConfirming.current) return;
    wasConfirming.current = false;
    if (!document.activeElement || document.activeElement === document.body) deleteRef.current?.focus();
  }, [confirming]);

  return (
    <footer className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3 max-md:px-4">
      <Button
        icon={Check}
        onClick={() => {
          setDeleteFailed(false);
          void track(task.id, commands.toggleDone(task.id)).catch(() => {});
        }}
      >
        {task.status === "done" ? "Reopen" : "Mark complete"}
      </Button>
      {confirming ? (
        <span role="group" aria-label="Delete this task?" className="flex animate-bt-fade items-center gap-1.5">
          <PanelButton
            ref={confirmRef}
            variant="confirm"
            onClick={remove}
            onKeyDown={(e) => {
              if (e.key !== "Escape") return;
              e.preventDefault();
              closePrompt();
            }}
          >
            Delete task
          </PanelButton>
          <PanelButton variant="quiet" className="h-[34px]" onClick={closePrompt}>
            Keep
          </PanelButton>
        </span>
      ) : (
        <PanelButton
          ref={deleteRef}
          variant="danger"
          onClick={() => {
            setDeleteFailed(false);
            setConfirming(true);
          }}
        >
          Delete
        </PanelButton>
      )}
      {deleteFailed && (
        <p role="alert" className="m-0 text-[12px] text-danger">
          Could not delete the task. Try again.
        </p>
      )}
      <span role="status" data-testid="save-state" className={cn("ml-auto font-mono text-[10.5px]", status === "failed" ? "text-danger" : "text-fg-3")}>
        {status === "idle" ? (
          <>
            saved · <span data-dynamic="time">{relativeTime(task.updatedAt, now)}</span>
          </>
        ) : (
          SAVE_TEXT[status]
        )}
      </span>
    </footer>
  );
}
