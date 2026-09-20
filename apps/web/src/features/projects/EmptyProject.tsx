"use client";

import { Plus } from "lucide-react";
import { useId, useRef, useState } from "react";
import { Pill } from "@/components/ui/Pill";
import { Button } from "@/components/ui/Button";
import type { Project } from "@/features/tasks/model/types";
import { useDirectory, useTaskCommands, useWorkspace } from "@/features/tasks/workspace/WorkspaceProvider";
import { ProjectDot } from "./ui/ProjectDot";

/** The selected project when it holds no task at all, whatever the filters say; otherwise null. */
export function useEmptyProject(): Project | null {
  const { state } = useWorkspace();
  const { projects } = useDirectory();
  const project = projects.find((p) => p.id === state.query.project);
  if (!project) return null;
  if (state.page) return state.page.project === project.id && state.page.projectHasTasks === false && !state.tasks.some((t) => t.project === project.id) ? project : null;
  if (state.load.status !== "ready") return null;
  return state.tasks.some((t) => t.project === project.id) ? null : project;
}

interface EmptyProjectProps {
  project: Project;
  /** The first task is saved, so this state is about to give way to the list or the board. */
  onFirstTask?: () => void;
}

/** What a project with no tasks shows instead of a list or board: an invitation to add the first one. */
export function EmptyProject({ project, onFirstTask }: EmptyProjectProps) {
  const commands = useTaskCommands();
  const { state, actions } = useWorkspace();
  const id = useId();
  const [title, setTitle] = useState("");
  const [failed, setFailed] = useState(false);
  /** Titles being saved: a second Enter on the same one must not create it twice. */
  const saving = useRef(new Set<string>());

  const add = () => {
    const text = title.trim();
    if (!text || saving.current.has(text)) return;
    saving.current.add(text);
    setFailed(false);
    commands
      .create({ title: text })
      .then(
        () => {
          setTitle((current) => (current.trim() === text ? "" : current));
          onFirstTask?.();
        },
        () => setFailed(true),
      )
      .finally(() => saving.current.delete(text));
  };

  return (
    <section aria-labelledby={`${id}-title`} aria-busy={state.load.status === "loading"} className="flex animate-bt-in flex-col items-start gap-4 px-6 py-14 max-md:px-4 max-md:py-10">
      {state.load.status === "error" && <div role="alert" className="flex items-center gap-3 text-[12.5px] text-danger">
        Could not refresh tasks. Your first-task draft is kept.
        <Button onClick={actions.reload}>Retry</Button>
      </div>}
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <ProjectDot tone={project.tone} />
          {project.key && <Pill>{project.key}</Pill>}
        </div>
        <h2 id={`${id}-title`} className="m-0 font-heading text-lg leading-[1.2] font-[var(--hw)] tracking-[var(--hls)]">
          {project.name} has no tasks yet
        </h2>
        <p className="m-0 max-w-[52ch] text-[13px] text-fg-3">Name the first one here, or use New task. Everything you add while this project is selected lands in it.</p>
      </div>
      <div className="flex w-[min(460px,100%)] flex-col gap-2">
        <label className="flex cursor-text items-center gap-3.5 rounded-bt border border-dashed border-line-2 px-3 py-1.5 text-fg-3 transition-[border-color,box-shadow] duration-[160ms] ease-bt focus-within:border-solid focus-within:border-acc focus-within:shadow-[0_0_0_3px_var(--acc-soft)]">
          <Plus aria-hidden="true" size={13} strokeWidth={2.5} className="flex-none" />
          <input
            name="first-task"
            autoComplete="off"
            value={title}
            aria-invalid={failed || undefined}
            aria-describedby={failed ? `${id}-error` : undefined}
            onChange={(e) => {
              setTitle(e.target.value);
              setFailed(false);
            }}
            onKeyDown={(e) => {
              // The Enter that confirms an input-method composition is not a submit.
              if (e.nativeEvent.isComposing) return;
              if (e.key === "Enter") add();
            }}
            aria-label="Name the first task"
            placeholder="Name the first task and press Enter"
            className="min-w-0 flex-1 border-0 bg-transparent py-1.5 text-sm text-fg placeholder:text-fg-3 placeholder:opacity-100 focus-visible:outline-none pointer-coarse:py-2.5"
          />
        </label>
        {failed && (
          <p id={`${id}-error`} role="alert" className="m-0 animate-bt-fade text-[12.5px] text-danger">
            Could not add the task. Press Enter to try again.
          </p>
        )}
      </div>
    </section>
  );
}
