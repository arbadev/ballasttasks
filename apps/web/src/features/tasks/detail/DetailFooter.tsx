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

const SAVE_TEXT: Record<Exclude<SaveStatus, "idle">, string> = { saving: "saving…", failed: "not saved" };

/** Complete or reopen, delete (asked twice, there is no undo), and the autosave indicator. */
export function DetailFooter({ task }: { task: Task }) {
  const now = useNow();
  const commands = useTaskCommands();
  const { track, saveStatus } = useDetailSession();
  const [confirming, setConfirming] = useState(false);
  const [deleteFailed, setDeleteFailed] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);

  const remove = () =>
    void track(commands.remove(task.id)).catch(() => {
      setConfirming(false);
      setDeleteFailed(true);
    });

  useEffect(() => {
    if (confirming) confirmRef.current?.focus();
  }, [confirming]);

  return (
    <footer className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3 max-md:px-4">
      <Button icon={Check} onClick={() => void track(commands.toggleDone(task.id)).catch(() => {})}>
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
              setConfirming(false);
            }}
          >
            Delete task
          </PanelButton>
          <PanelButton variant="quiet" className="h-[34px]" onClick={() => setConfirming(false)}>
            Keep
          </PanelButton>
        </span>
      ) : (
        <PanelButton
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
      <span role="status" data-testid="save-state" className={cn("ml-auto font-mono text-[10.5px]", saveStatus === "failed" ? "text-danger" : "text-fg-3")}>
        {saveStatus === "idle" ? (
          <>
            saved · <span data-dynamic="time">{relativeTime(task.updatedAt, now)}</span>
          </>
        ) : (
          SAVE_TEXT[saveStatus]
        )}
      </span>
    </footer>
  );
}
