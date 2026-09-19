"use client";

import { FileText, Image as ImageIcon, Link as LinkIcon, Paperclip, type LucideIcon } from "lucide-react";
import { useId, useRef, useState } from "react";
import type { Attachment, AttachmentKind, Task } from "../model/types";
import { useTaskCommands } from "../workspace/WorkspaceProvider";
import { PanelButton, SECTION_LABEL } from "./controls";
import { useDetailSession } from "./DetailSession";
import { LinkForm } from "./LinkForm";

const KINDS: Record<AttachmentKind, { icon: LucideIcon; label: string }> = {
  pdf: { icon: FileText, label: "PDF" },
  image: { icon: ImageIcon, label: "Image" },
  link: { icon: LinkIcon, label: "Link" },
};

/** The task's files and links. Links are added here; file upload is a later piece. */
export function AttachmentsSection({ task }: { task: Task }) {
  const headingId = useId();
  const formId = useId();
  const uploadHintId = useId();
  const commands = useTaskCommands();
  const { track } = useDetailSession();
  const [adding, setAdding] = useState(false);
  const addLinkRef = useRef<HTMLButtonElement>(null);
  const count = task.attachments.length;

  const closeForm = () => {
    setAdding(false);
    addLinkRef.current?.focus();
  };

  const addLink = async (attachment: Attachment) => {
    await track(commands.addAttachment(task.id, attachment));
    closeForm();
  };

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2.5 border-t border-line pt-[18px]">
      <div className="flex flex-wrap items-center gap-3">
        <h3 id={headingId} className={SECTION_LABEL}>
          Attachments
        </h3>
        <span data-testid="attachment-count" className="font-mono text-[12px] text-fg-2">
          {count}
        </span>
        <div className="ml-auto flex gap-1.5">
          {/* Present as designed, but upload is not built yet: dimmed, inert, and it says why. */}
          <button
            type="button"
            aria-disabled="true"
            aria-describedby={uploadHintId}
            title="File upload is not available yet."
            className="inline-flex h-[30px] flex-none cursor-not-allowed items-center gap-[7px] rounded-bt border border-line-2 bg-card px-2.5 text-[12.5px] font-medium text-fg opacity-50 pointer-coarse:min-h-11"
          >
            <Paperclip aria-hidden="true" size={13} strokeWidth={2} />
            Attach file
          </button>
          <span id={uploadHintId} hidden>
            File upload is not available yet.
          </span>
          <PanelButton ref={addLinkRef} variant="secondary" icon={LinkIcon} aria-expanded={adding} aria-controls={formId} onClick={() => setAdding((open) => !open)} className="h-[30px] px-2.5">
            Add link
          </PanelButton>
        </div>
      </div>

      {adding && <LinkForm id={formId} onAdd={addLink} onCancel={closeForm} />}

      {count > 0 && (
        <ul aria-label="Attachments" className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(min(230px,100%),1fr))] gap-2 p-0">
          {task.attachments.map((attachment, i) => {
            const { icon: Icon, label } = KINDS[attachment.kind];
            return (
              <li
                key={`${attachment.name}-${i}`}
                className="flex min-w-0 animate-[bt-in_.3s_var(--ease)_both] items-center gap-2.5 rounded-bt border border-line bg-card p-2.5 transition-[border-color,transform] duration-[160ms] ease-bt hover:-translate-y-px hover:border-line-2"
              >
                <span role="img" aria-label={label} className="grid size-9 flex-none place-items-center rounded-bt-sm bg-card-2 text-fg-2">
                  <Icon aria-hidden="true" size={16} strokeWidth={2} />
                </span>
                <div className="flex min-w-0 flex-col gap-0.5">
                  <span className="truncate text-[13px] font-medium">{attachment.name}</span>
                  <span className="truncate font-mono text-[10.5px] text-fg-3">{attachment.meta}</span>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {count === 0 && !adding && (
        <p data-testid="attachments-empty" className="m-0 rounded-bt border border-dashed border-line-2 px-3.5 py-[18px] text-[12.5px] text-fg-3">
          Nothing attached yet. Add a link to a PDF, a screenshot or a thread the assistant can read.
        </p>
      )}
    </section>
  );
}
