"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type RefObject } from "react";
import { Pencil } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import type { Project } from "@/features/tasks/model/types";
import { useDirectory, useWorkspace } from "@/features/tasks/workspace/WorkspaceProvider";
import { ProjectRejectedError, type ProjectEdit } from "@/features/tasks/services/types";
import { normalizeName, validateProjectName } from "./model/rules";
import { Field, FieldMessage } from "./ui/Field";
import { ModalDialog } from "./ui/ModalDialog";
import { ProjectColour } from "./ui/ProjectColour";

export function EditProjectControl({ project }: { project: Project }) {
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  return <>
    <IconButton buttonRef={opener} aria-haspopup="dialog" icon={Pencil} label="Edit project" onClick={() => setOpen(true)} />
    {open && <EditProjectDialog key={project.id} project={project} opener={opener} onClose={() => setOpen(false)} />}
  </>;
}

function EditProjectDialog({ project, opener, onClose }: { project: Project; opener: RefObject<HTMLElement | null>; onClose: () => void }) {
  const id = useId();
  const { projects } = useDirectory();
  const { actions } = useWorkspace();
  const [name, setName] = useState(project.name);
  const [tone, setTone] = useState(project.tone);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const [invalid, setInvalid] = useState<{ message: string }>();
  const active = useRef(true);
  const sending = useRef(false);
  const nameInput = useRef<HTMLInputElement>(null);
  const focusName = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  // Each outcome leaves the keyboard where the next action is: the name to correct, or Retry.
  useEffect(() => {
    if (pending) return;
    if (focusName.current) nameInput.current?.focus();
    focusName.current = false;
  }, [pending, invalid]);
  useEffect(() => {
    if (error) document.getElementById(`${id}-retry`)?.focus();
  }, [error, id]);
  const refuse = (message?: string) => {
    focusName.current = Boolean(message);
    setInvalid(message ? { message } : undefined);
  };
  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (sending.current) return;
    setError(undefined);
    const normalized = normalizeName(name);
    // A name left as the directory stores it is never re-judged by the rules for a new one.
    const renamed = normalized !== project.name;
    const recoloured = tone !== project.tone;
    const found = renamed ? validateProjectName(name, projects.filter((item) => item.id !== project.id)) : undefined;
    refuse(found);
    if (found) return;
    if (!renamed && !recoloured) { onClose(); return; }
    const edit: ProjectEdit = {};
    if (renamed) edit.name = normalized;
    if (recoloured) edit.tone = tone;
    sending.current = true;
    setPending(true);
    try {
      await actions.updateProject(project.id, edit);
      if (active.current) onClose();
    } catch (failure) {
      if (active.current) {
        if (failure instanceof ProjectRejectedError) refuse(failure.errors.name ?? failure.message);
        else setError(failure instanceof Error ? failure.message : "Please try again.");
      }
    } finally {
      sending.current = false;
      if (active.current) setPending(false);
    }
  };
  return <ModalDialog labelledBy={`${id}-title`} opener={opener} onDismiss={onClose} dismissable={!pending}>
    <form aria-labelledby={`${id}-title`} aria-busy={pending} noValidate onSubmit={submit} className="flex flex-col gap-4 p-5">
      <h2 id={`${id}-title`} className="m-0 font-heading text-base leading-[1.2] font-[var(--hw)] tracking-[var(--hls)]">Edit project</h2>
      <Field id={`${id}-name`} label="Name" value={name} onChange={(value) => { setName(value); refuse(undefined); }} disabled={pending} autoFocus invalid={Boolean(invalid)} describedBy={invalid ? `${id}-invalid` : undefined} inputRef={nameInput} />
      {invalid && <FieldMessage id={`${id}-invalid`} tone="error">{invalid.message}</FieldMessage>}
      <div className="flex items-start gap-4">
        <label className="flex w-24 flex-none flex-col gap-1.5 text-[11.5px] text-fg-3">Key
          <input id={`${id}-key`} aria-describedby={`${id}-key-hint`} readOnly value={project.key ?? ""} className="h-[34px] w-full rounded-bt border border-line bg-card px-2.5 font-mono text-[12.5px] text-fg" />
        </label>
        <ProjectColour id={id} tone={tone} setTone={setTone} pending={pending} />
      </div>
      <FieldMessage id={`${id}-key-hint`}>The key stays the same, including on existing tasks.</FieldMessage>
      {error && <div role="alert" className="rounded-bt bg-danger-soft p-3 text-[12.5px] text-fg">Could not save the project. {error} <Button id={`${id}-retry`} variant="ghost" disabled={pending} onClick={() => void submit()}>Retry</Button></div>}
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="ghost" disabled={pending} onClick={onClose}>Cancel</Button>
        <Button type="submit" disabled={pending}>{pending ? "Saving…" : "Save changes"}</Button>
      </div>
    </form>
  </ModalDialog>;
}
