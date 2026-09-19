"use client";

import { useId, useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { relativeTime } from "../model/time";
import type { Person, Task } from "../model/types";
import { useDirectory, useNow, useTaskCommands } from "../workspace/WorkspaceProvider";
import { BOX_INPUT, PanelButton, SECTION_LABEL } from "./controls";
import { useDetailSession, useDraft } from "./DetailSession";

const ASSISTANT: Person = { id: "ai", name: "Assistant", initials: "AI", role: "system" };

/** The task's history, oldest first: log lines and comments, then the box to add one. */
export function ActivitySection({ task }: { task: Task }) {
  const headingId = useId();
  const now = useNow();
  const { people, currentUser } = useDirectory();
  const commands = useTaskCommands();
  const { track } = useDetailSession();
  const [comment, setComment] = useDraft(`comment:${task.id}`);
  const [failed, setFailed] = useState(false);

  const entries = [...task.activity].sort((a, b) => a.at - b.at);
  const person = (id: string) => people.find((p) => p.id === id) ?? (id === ASSISTANT.id ? ASSISTANT : null);
  const tone = (id: string) => (id === ASSISTANT.id ? "solid" : id === currentUser?.id ? "accent" : "neutral");

  const post = () => {
    const text = comment.trim();
    if (!text) return;
    setComment("");
    setFailed(false);
    void track(commands.addComment(task.id, text)).catch(() => {
      setComment(text);
      setFailed(true);
    });
  };

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
                <Avatar initials={who?.initials ?? "?"} tone={tone(entry.who)} />
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
          <Avatar initials={currentUser?.initials ?? ""} tone="accent" />
        </span>
        <textarea
          aria-label="Write a comment"
          placeholder="Write a comment — Enter to post"
          rows={1}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          onKeyDown={(e) => {
            // Shift+Enter falls through to the textarea and breaks the line.
            if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
            e.preventDefault();
            post();
          }}
          className={`${BOX_INPUT} field-sizing-content block max-h-40 min-h-[34px] min-w-0 flex-1 resize-none px-3 py-[6px] text-[13px] leading-5`}
        />
        <PanelButton variant="secondary" className="h-[34px] px-3" onClick={post}>
          Comment
        </PanelButton>
      </div>
      {failed && (
        <p role="alert" className="m-0 text-[12px] text-danger">
          Could not post the comment. It is back in the box; press Enter to try again.
        </p>
      )}
    </section>
  );
}
