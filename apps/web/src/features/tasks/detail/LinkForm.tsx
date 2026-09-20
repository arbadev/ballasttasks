"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import type { Attachment } from "../model/types";
import { BOX_INPUT, FieldLabel, PanelButton } from "./controls";
import { linkAttachment } from "./model/linkAttachment";

interface LinkFormProps {
  id: string;
  /** Resolves once the link is saved; a rejection leaves the form open with a message. */
  onAdd: (attachment: Attachment) => Promise<void>;
  onCancel: () => void;
}

/** URL plus optional title. Escape closes the form, not the panel around it. */
export function LinkForm({ id, onAdd, onCancel }: LinkFormProps) {
  const fieldId = useId();
  const urlRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => urlRef.current?.focus(), []);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const result = linkAttachment(url, title);
    if (!result.ok) {
      setError(result.error);
      urlRef.current?.focus();
      return;
    }
    setSaving(true);
    onAdd(result.attachment).catch(() => {
      setSaving(false);
      setError("Could not add the link. Try again.");
    });
  };

  return (
    <form
      id={id}
      aria-label="Add a link"
      noValidate
      onSubmit={submit}
      onKeyDown={(e) => {
        if (e.key !== "Escape") return;
        // Handled here: the panel's own Escape listener skips events already dealt with.
        e.preventDefault();
        onCancel();
      }}
      className="flex animate-[bt-in_.25s_var(--ease)] flex-col gap-2.5 rounded-bt border border-line bg-card p-3"
    >
      <div className="grid grid-cols-2 gap-2.5 max-md:grid-cols-1">
        <div className="flex flex-col gap-1.5">
          <FieldLabel htmlFor={`${fieldId}-url`}>Link URL</FieldLabel>
          <input
            ref={urlRef}
            id={`${fieldId}-url`}
            name="url"
            type="url"
            inputMode="url"
            autoComplete="off"
            placeholder="https://"
            value={url}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${fieldId}-error` : undefined}
            onChange={(e) => {
              setUrl(e.target.value);
              setError(null);
            }}
            className={`${BOX_INPUT} h-[34px] bg-panel px-3 text-[13px] pointer-coarse:h-11`}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <FieldLabel htmlFor={`${fieldId}-title`}>Title (optional)</FieldLabel>
          <input
            id={`${fieldId}-title`}
            name="link-title"
            autoComplete="off"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className={`${BOX_INPUT} h-[34px] bg-panel px-3 text-[13px] pointer-coarse:h-11`}
          />
        </div>
      </div>
      {error && (
        <p id={`${fieldId}-error`} role="alert" className="m-0 text-[12px] text-danger">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <PanelButton type="submit" variant="secondary" disabled={saving} className="h-[30px] px-3">
          Add
        </PanelButton>
        <PanelButton variant="quiet" className="h-[30px]" onClick={onCancel}>
          Cancel
        </PanelButton>
      </div>
    </form>
  );
}
