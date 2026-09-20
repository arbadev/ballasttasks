"use client";

import { Download, FileText, Image as ImageIcon, Link as LinkIcon, Paperclip, Trash2, type LucideIcon } from "lucide-react";
import { useId, useRef, useState } from "react";
import type { Attachment, AttachmentKind, Task } from "../model/types";
import { useTaskCommands } from "../workspace/WorkspaceProvider";
import { PanelButton, SECTION_LABEL } from "./controls";
import { useDetailSession } from "./DetailSession";
import { LinkForm } from "./LinkForm";
import { FILE_ACCEPT, fileAttachment } from "./model/fileAttachment";

const KINDS: Record<AttachmentKind, { icon: LucideIcon; label: string }> = {
  pdf: { icon: FileText, label: "PDF" },
  image: { icon: ImageIcon, label: "Image" },
  link: { icon: LinkIcon, label: "Link" },
};

/** The task's files and navigable links, saved through the injected service. */
export function AttachmentsSection({ task }: { task: Task }) {
  const headingId = useId();
  const formId = useId();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadBusy = useRef(false);
  const [uploading, setUploading] = useState<Attachment | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const actionBusy = useRef(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const commands = useTaskCommands();
  const { track } = useDetailSession();
  const [adding, setAdding] = useState(false);
  const addLinkRef = useRef<HTMLButtonElement>(null);
  const attachments = uploading ? [...task.attachments, uploading] : task.attachments;
  const count = attachments.length;

  const upload = async (file?: File) => {
    if (!file || uploadBusy.current) return;
    const result = fileAttachment(file);
    if ("error" in result) {
      setUploadError(result.error);
      return;
    }
    uploadBusy.current = true;
    setUploadError(null);
    setUploading(result.uploading);
    try {
      await track(task.id, commands.addAttachment(task.id, result.attachment, file));
    } catch {
      setUploadError("Could not attach the file. Try again.");
    } finally {
      uploadBusy.current = false;
      setUploading(null);
    }
  };

  const attachmentAction = async (attachment: Attachment, action: "download" | "remove") => {
    if (!attachment.id || actionBusy.current) return;
    actionBusy.current = true;
    setBusyId(attachment.id);
    setActionError(null);
    try {
      if (action === "remove" && commands.removeAttachment) {
        await track(task.id, commands.removeAttachment(task.id, attachment.id));
      } else if (action === "download" && commands.downloadAttachment) {
        const blob = await commands.downloadAttachment(task.id, attachment.id);
        const url = URL.createObjectURL(blob);
        try {
          const link = document.createElement("a");
          link.href = url;
          link.download = attachment.name;
          link.click();
        } finally {
          setTimeout(() => URL.revokeObjectURL(url), 0);
        }
      }
    } catch {
      setActionError(`Could not ${action} the attachment. Try again.`);
    } finally {
      actionBusy.current = false;
      setBusyId(null);
    }
  };

  const closeForm = () => {
    setAdding(false);
    addLinkRef.current?.focus();
  };

  const addLink = async (attachment: Attachment) => {
    await track(task.id, commands.addAttachment(task.id, attachment));
    closeForm();
  };

  return (
    <section
      aria-labelledby={headingId}
      onDragOver={(e) => { e.preventDefault(); }}
      onDrop={(e) => { e.preventDefault(); void upload(e.dataTransfer.files[0]); }}
      className="flex flex-col gap-2.5 border-t border-line pt-[18px]"
    >
      <div className="flex flex-wrap items-center gap-3">
        <h3 id={headingId} className={SECTION_LABEL}>
          Attachments
        </h3>
        <span data-testid="attachment-count" className="font-mono text-[12px] text-fg-2">
          {count}
        </span>
        <div className="ml-auto flex gap-1.5">
          <input
            ref={fileInputRef}
            type="file"
            name="attachment"
            aria-label="Choose a file to attach"
            accept={FILE_ACCEPT}
            tabIndex={-1}
            className="sr-only"
            onChange={(e) => {
              const file = e.currentTarget.files?.[0];
              e.currentTarget.value = "";
              void upload(file);
            }}
          />
          <PanelButton variant="secondary" icon={Paperclip} disabled={!!uploading} onClick={() => fileInputRef.current?.click()} className="h-[30px] px-2.5">
            Attach file
          </PanelButton>
          <PanelButton ref={addLinkRef} variant="secondary" icon={LinkIcon} aria-expanded={adding} aria-controls={adding ? formId : undefined} onClick={() => setAdding((open) => !open)} className="h-[30px] px-2.5">
            Add link
          </PanelButton>
        </div>
      </div>

      {uploadError && <p role="alert" className="m-0 text-[12px] text-danger">{uploadError}</p>}
      {actionError && <p role="alert" className="m-0 text-[12px] text-danger">{actionError}</p>}
      {adding && <LinkForm id={formId} onAdd={addLink} onCancel={closeForm} />}

      {count > 0 && (
        <ul aria-label="Attachments" className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(min(230px,100%),1fr))] gap-2 p-0">
          {attachments.map((attachment, i) => {
            const { icon: Icon, label } = KINDS[attachment.kind];
            const content = <>
              <span role="img" aria-label={label} className="grid size-9 flex-none place-items-center rounded-bt-sm bg-card-2 text-fg-2">
                <Icon aria-hidden="true" size={16} strokeWidth={2} />
              </span>
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-[13px] font-medium">{attachment.name}</span>
                <span className="truncate font-mono text-[10.5px] text-fg-3">{attachment.meta}</span>
              </div>
            </>;
            return (
              <li
                key={attachment.id ?? `${attachment.name}-${i}`}
                className="flex min-w-0 animate-[bt-in_.3s_var(--ease)_both] items-center gap-2.5 rounded-bt border border-line bg-card p-2.5 transition-[border-color,transform] duration-[160ms] ease-bt hover:-translate-y-px hover:border-line-2"
              >
                {attachment.kind === "link" ? (
                  <a href={attachment.url} target="_blank" rel="noopener noreferrer" className="-m-2.5 flex min-w-0 flex-1 items-center gap-2.5 rounded-bt p-2.5 text-inherit no-underline">{content}</a>
                ) : <div className="flex min-w-0 flex-1 items-center gap-2.5">{content}</div>}
                {attachment.id && <div className="ml-auto flex shrink-0 gap-1">
                  {attachment.kind !== "link" && commands.downloadAttachment && <PanelButton variant="quiet" icon={Download} aria-label={`Download ${attachment.name}`} disabled={busyId !== null} onClick={() => void attachmentAction(attachment, "download")} className="size-8 p-0" />}
                  {commands.removeAttachment && <PanelButton variant="quiet" icon={Trash2} aria-label={`Remove attachment: ${attachment.name}`} disabled={busyId !== null} onClick={() => void attachmentAction(attachment, "remove")} className="size-8 p-0" />}
                </div>}
              </li>
            );
          })}
        </ul>
      )}

      {count === 0 && !adding && (
        <p data-testid="attachments-empty" className="m-0 mt-2.5 rounded-bt border border-dashed border-line-2 px-3.5 py-[18px] text-[12.5px] text-fg-3">
          Drop files here, or paste a link — PDFs, screenshots and threads the assistant can read.
        </p>
      )}
    </section>
  );
}
