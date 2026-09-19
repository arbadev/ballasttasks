"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type RefObject } from "react";
import { Button } from "@/components/ui/Button";
import type { ProjectTone } from "@/features/tasks/model/types";
import type { ProjectFieldErrors } from "@/features/tasks/services/types";
import { useDirectory } from "@/features/tasks/workspace/WorkspaceProvider";
import { cn } from "@/lib/cn";
import { KEY_MAX, PROJECT_TONES, cleanKey, normalizeName, suggestKey, suggestTone, validateProject } from "./model/rules";
import { Field, FieldMessage } from "./ui/Field";
import { ModalDialog } from "./ui/ModalDialog";
import { ProjectDot } from "./ui/ProjectDot";
import { useCreateProject } from "./useCreateProject";

const TONE_NAMES: Record<ProjectTone, string> = { accent: "Lime", info: "Blue", ok: "Green", warn: "Amber", muted: "Grey" };

interface NewProjectDialogProps {
  /** The control that opened the dialog; it gets the focus back. */
  opener: RefObject<HTMLElement | null>;
  /** Cancel, Escape or the backdrop. */
  onClose: () => void;
  /** The project is stored, listed and selected. */
  onCreated: () => void;
}

export function NewProjectDialog({ opener, onClose, onCreated }: NewProjectDialogProps) {
  const { projects } = useDirectory();
  const { state, create } = useCreateProject();
  const id = useId();
  const nameInput = useRef<HTMLInputElement>(null);
  const keyInput = useRef<HTMLInputElement>(null);
  /** The field to focus once the form is interactive again. */
  const focusNext = useRef<"name" | "key" | null>(null);

  const [name, setName] = useState("");
  /** Null while the key still follows the name; a string once it has been edited by hand. */
  const [typedKey, setTypedKey] = useState<string | null>(null);
  const [tone, setTone] = useState<ProjectTone>(() => suggestTone(projects));
  const [errors, setErrors] = useState<ProjectFieldErrors>({});

  const key = typedKey ?? suggestKey(name, projects.flatMap((p) => p.key ?? []));
  const pending = state.status === "pending";
  const failed = state.status === "failed";

  // Each outcome leaves the keyboard where the next action is: the field to correct, or Retry.
  useEffect(() => {
    if (pending) return;
    if (failed) document.getElementById(`${id}-retry`)?.focus();
    else if (focusNext.current) (focusNext.current === "name" ? nameInput : keyInput).current?.focus();
    focusNext.current = null;
  }, [pending, failed, errors, id]);

  const showErrors = (found: ProjectFieldErrors) => {
    focusNext.current = found.name ? "name" : found.key ? "key" : null;
    setErrors(found);
  };

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (pending) return;
    const found = validateProject({ name, key }, projects);
    showErrors(found);
    if (found.name || found.key) return;
    const result = await create({ name: normalizeName(name), key, tone });
    if (result.created) onCreated();
    else if (result.errors) showErrors(result.errors);
  };

  return (
    <ModalDialog labelledBy={`${id}-title`} opener={opener} onDismiss={onClose} dismissable={!pending} backdropTestId="new-project-backdrop">
      <form aria-labelledby={`${id}-title`} aria-busy={pending} noValidate onSubmit={submit} className="flex flex-col gap-4 p-5">
        <div className="flex flex-col gap-1">
          <h2 id={`${id}-title`} className="m-0 font-heading text-base leading-[1.2] font-[var(--hw)] tracking-[var(--hls)]">
            New project
          </h2>
          <p className="m-0 text-[12.5px] text-fg-3">A project groups tasks under one name, key and colour.</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Field
            id={`${id}-name`}
            label="Name"
            value={name}
            onChange={(value) => {
              setName(value);
              // The key follows the name until it is edited, so its message may be stale too.
              setErrors((e) => ({ key: typedKey === null ? undefined : e.key }));
            }}
            invalid={Boolean(errors.name)}
            describedBy={errors.name ? `${id}-name-error` : undefined}
            disabled={pending}
            autoFocus
            inputRef={nameInput}
          />
          {errors.name && (
            <FieldMessage id={`${id}-name-error`} tone="error">
              {errors.name}
            </FieldMessage>
          )}
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-start gap-4">
            <Field
              id={`${id}-key`}
              label="Key"
              value={key}
              onChange={(value) => {
                setTypedKey(cleanKey(value));
                setErrors((e) => ({ name: e.name }));
              }}
              invalid={Boolean(errors.key)}
              describedBy={errors.key ? `${id}-key-hint ${id}-key-error` : `${id}-key-hint`}
              disabled={pending}
              maxLength={KEY_MAX}
              mono
              inputRef={keyInput}
              className="w-24 flex-none"
            />
            <div className="flex min-w-0 flex-col gap-1.5">
              <span id={`${id}-tone-label`} className="text-[11.5px] text-fg-3">
                Colour
              </span>
              <div role="radiogroup" aria-labelledby={`${id}-tone-label`} className="flex h-[34px] gap-0.5 rounded-bt border border-line bg-card p-[3px] pointer-coarse:h-11">
                {PROJECT_TONES.map((option) => (
                  <label
                    key={option}
                    title={TONE_NAMES[option]}
                    className={cn(
                      // The radio itself is invisible, so the label carries its focus ring.
                      "relative grid aspect-square h-full cursor-pointer place-items-center rounded-[calc(var(--r)-3px)] transition-colors duration-[160ms] ease-bt has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-acc has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50",
                      option === tone ? "bg-card-2 shadow-1 ring-1 ring-line-2 ring-inset" : "hover:bg-card-2",
                    )}
                  >
                    <input
                      type="radio"
                      name={`${id}-tone`}
                      value={option}
                      aria-label={TONE_NAMES[option]}
                      checked={option === tone}
                      onChange={() => setTone(option)}
                      disabled={pending}
                      className="absolute size-0 opacity-0"
                    />
                    <ProjectDot tone={option} className={cn("transition-[width,height] duration-[160ms] ease-bt", option === tone ? "size-3" : "size-2")} />
                  </label>
                ))}
              </div>
            </div>
          </div>
          <FieldMessage id={`${id}-key-hint`}>
            2 to {KEY_MAX} letters, used in task ids like <span className="font-mono text-fg-2">{key || "BT"}-04</span>.
          </FieldMessage>
          {errors.key && (
            <FieldMessage id={`${id}-key-error`} tone="error">
              {errors.key}
            </FieldMessage>
          )}
        </div>

        {state.status === "failed" && (
          <div role="alert" className="flex animate-bt-in items-center gap-3 rounded-bt bg-danger-soft py-1.5 pr-1.5 pl-3 text-[12.5px] text-fg">
            <p className="m-0 min-w-0 flex-1">
              Could not create the project. <span className="text-fg-2">{state.message}</span>
            </p>
            <Button id={`${id}-retry`} variant="ghost" onClick={() => void submit()} className="flex-none text-fg! hover:bg-card-2!">
              Retry
            </Button>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose} disabled={pending} className="h-[34px]! px-3!">
            Cancel
          </Button>
          <Button type="submit" disabled={pending}>
            {/* The design's "working" cue: the pulsing dot it shows while the assistant drafts steps. */}
            {pending && <span aria-hidden="true" className="size-1.5 animate-bt-pulse rounded-full bg-current" />}
            {pending ? "Creating…" : "Create project"}
          </Button>
        </div>
      </form>
    </ModalDialog>
  );
}
