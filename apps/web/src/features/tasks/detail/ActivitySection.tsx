"use client";

import { useId } from "react";
import { cn } from "@/lib/cn";
import { relativeTime } from "../model/time";
import type { Person, Task } from "../model/types";
import { useDirectory, useNow, useTaskCommands } from "../workspace/WorkspaceProvider";
import { ActionError, BOX_INPUT, PanelButton, SECTION_LABEL } from "./controls";
import { useComposer, useDetailSession } from "./DetailSession";

const AVATAR_TONES = {
  neutral: "bg-card-2 text-fg-2",
  accent: "bg-acc-soft text-acc",
  solid: "bg-acc text-acc-fg",
};

/** The timeline sets its initials a touch smaller (9px) than the shared 24px Avatar does. */
function TimelineAvatar({ initials, tone, tracked = true }: { initials: string; tone: keyof typeof AVATAR_TONES; tracked?: boolean }) {
  return (
    <span aria-hidden="true" className={cn("grid size-6 flex-none place-items-center rounded-bt-av border border-line text-[9px] font-semibold", tracked && "tracking-[.02em]", AVATAR_TONES[tone])}>
      {initials}
    </span>
  );
}

const ASSISTANT: Person = { id: "ai", name: "Assistant", initials: "AI", role: "system" };

/** The task's history, oldest first: log lines and comments, then the box to add one. */
export function ActivitySection({ task }: { task: Task }) {
  const headingId = useId();
  const now = useNow();
  const { people, currentUser } = useDirectory();
  const commands = useTaskCommands();
  const { track } = useDetailSession();
  const box = useComposer(`comment:${task.id}`, (text) => track(task.id, commands.addComment(task.id, text)), () => track(task.id, commands.refresh(task.id), "refresh"));

  const entries = [...task.activity].sort((a, b) => a.at - b.at);
  const person = (id: string) => people.find((p) => p.id === id) ?? (id === ASSISTANT.id ? ASSISTANT : null);
  const tone = (id: string): keyof typeof AVATAR_TONES => (id === ASSISTANT.id ? "solid" : id === currentUser?.id ? "accent" : "neutral");


  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3.5 border-t border-line pt-[18px]">
      <h3 id={headingId} className={SECTION_LABEL}>
        Activity
      </h3>

      {entries.length > 0 && (
        <ol aria-label="Activity" className="m-0 flex list-none flex-col gap-3.5 p-0">
          {entries.map((entry, i) => {
            const who = person(entry.who);
            return (
              <li key={`${entry.at}-${i}`} data-kind={entry.type} className="flex items-start gap-2.5">
                <TimelineAvatar initials={who?.initials ?? "?"} tone={tone(entry.who)} />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <div className="flex flex-wrap items-baseline gap-2 text-[12px] text-fg-3">
                    <span className="font-medium text-fg">{who?.name ?? "Unknown"}</span>
                    <span data-dynamic="time" className="font-mono text-[10.5px]">
                      {relativeTime(entry.at, now)}
                    </span>
                  </div>
                  {entry.type === "comment" ? (
                    <div className="rounded-bt border border-line bg-card px-3 py-2.5 text-[13px] leading-[1.55] text-pretty break-words whitespace-pre-wrap">{entry.text}</div>
                  ) : (
                    <div className="text-[12.5px] break-words text-fg-2">{entry.text}</div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      <div className="flex items-start gap-2.5">
        <span className="flex h-[34px] flex-none items-center">
          <TimelineAvatar initials={currentUser?.initials ?? ""} tone="accent" tracked={false} />
        </span>
        <textarea
          aria-label="Write a comment"
          name="comment"
          placeholder="Write a comment — Enter to post"
          rows={1}
          value={box.text}
          aria-busy={box.busy}
          onChange={(e) => box.setText(e.target.value)}
          onKeyDown={(e) => {
            // Shift+Enter falls through to the textarea and breaks the line.
            if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
            e.preventDefault();
            box.submit();
          }}
          className={`${BOX_INPUT} field-sizing-content block max-h-40 min-h-[34px] min-w-0 flex-1 resize-none px-3 py-[6px] text-[13px] leading-5`}
        />
        <PanelButton variant="secondary" className="h-[34px] px-3" disabled={box.busy} onClick={box.submit}>
          Comment
        </PanelButton>
      </div>
      {box.sending && (
        <p role="status" className="m-0 text-[12px] text-fg-3">
          Posting comment… the box takes the next one when this lands.
        </p>
      )}
      {box.refreshing && <p role="status" className="m-0 text-[12px] text-fg-3">Reloading the saved comment…</p>}
      {box.failed !== null && (box.refreshRequired ? (
        <ActionError onRetry={box.retry} retryLabel="Reload task">
          The comment was saved, but the task could not be reloaded. Reload to see it; no comment will be sent again.
        </ActionError>
      ) : (
        <ActionError onRetry={box.retry} onDismiss={box.dismiss}>
          Could not post the comment. It is kept, and neither Enter nor Comment sends until you retry or dismiss it.
        </ActionError>
      ))}
    </section>
  );
}
