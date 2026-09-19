"use client";

import { useId } from "react";
import { STATUSES } from "../model/statuses";
import { relativeTime } from "../model/time";
import type { Priority, Task, TaskStatus } from "../model/types";
import { useDirectory, useNow, useTaskCommands } from "../workspace/WorkspaceProvider";
import { BOX_INPUT, FieldLabel, PropertySelect, SaveError } from "./controls";
import { useDetailSession } from "./DetailSession";
import { AUTOSAVE_DELAY_MS, useAutosaveField } from "./useAutosaveField";

const STATUS_OPTIONS = STATUSES.map((s) => ({ value: s.id, label: s.name }));
const PRIORITY_OPTIONS = ([0, 1, 2, 3] as const).map((p) => ({ value: String(p), label: `P${p}` }));
/** The assistant writes activity but is never anyone's assignee. */
const ASSISTANT_ROLE = "system";

const clampImportance = (n: number) => Math.max(0, Math.min(100, Math.round(n)));

/** The property column: every control saves on change, none has a Save button. */
export function PropertiesPanel({ task }: { task: Task }) {
  const id = useId();
  const now = useNow();
  const { people, projects } = useDirectory();
  const commands = useTaskCommands();
  const { track } = useDetailSession();

  const status = useAutosaveField({ saved: task.status, save: (v: TaskStatus) => track(commands.move(task.id, v)) });
  const assignee = useAutosaveField({ saved: task.assignee, save: (v: string | null) => track(commands.update(task.id, { assignee: v })) });
  const due = useAutosaveField({ saved: task.due, save: (v: string | null) => track(commands.update(task.id, { due: v })) });
  const prio = useAutosaveField({ saved: task.prio, save: (v: Priority) => track(commands.update(task.id, { prio: v })) });
  const project = useAutosaveField({ saved: task.project, save: (v: string) => track(commands.update(task.id, { project: v })) });
  // Held as text while typing so the field can be emptied; an empty box is simply not saved.
  const importance = useAutosaveField({
    saved: String(task.importance),
    save: (v: string) => (v.trim() === "" || Number.isNaN(Number(v)) ? Promise.resolve() : track(commands.update(task.id, { importance: clampImportance(Number(v)) }))),
    delay: AUTOSAVE_DELAY_MS,
  });

  const assigneeOptions = [{ value: "", label: "Unassigned" }, ...people.filter((p) => p.role !== ASSISTANT_ROLE).map((p) => ({ value: p.id, label: p.name }))];
  const projectOptions = projects.map((p) => ({ value: p.id, label: p.name }));

  return (
    <aside
      aria-label="Properties"
      className="flex min-w-[240px] flex-[0_1_272px] flex-col gap-3.5 border-l border-line bg-bg px-5 py-[22px] max-md:flex-[1_1_100%] max-md:border-t max-md:border-l-0 max-md:px-4"
    >
      <div className="flex flex-col gap-1.5">
        <FieldLabel htmlFor={`${id}-status`}>Status</FieldLabel>
        <PropertySelect id={`${id}-status`} name="status" value={status.value} options={STATUS_OPTIONS} onChange={(v) => status.change(v as TaskStatus)} />
        {status.failed && <SaveError what="status" onRetry={status.retry} />}
      </div>

      <div className="flex flex-col gap-1.5">
        <FieldLabel htmlFor={`${id}-assignee`}>Assignee</FieldLabel>
        <PropertySelect id={`${id}-assignee`} name="assignee" value={assignee.value ?? ""} options={assigneeOptions} onChange={(v) => assignee.change(v || null)} />
        {assignee.failed && <SaveError what="assignee" onRetry={assignee.retry} />}
      </div>

      <div className="flex flex-col gap-1.5">
        <FieldLabel htmlFor={`${id}-due`}>Due date</FieldLabel>
        <input
          id={`${id}-due`}
          name="due"
          type="date"
          value={due.value ?? ""}
          onChange={(e) => due.change(e.target.value || null)}
          className={`${BOX_INPUT} h-[34px] px-2.5 font-mono text-[13px] pointer-coarse:h-11`}
        />
        {due.failed && <SaveError what="due date" onRetry={due.retry} />}
      </div>

      <div className="grid grid-cols-2 gap-2.5">
        <div className="flex flex-col gap-1.5">
          <FieldLabel htmlFor={`${id}-prio`}>Priority</FieldLabel>
          <PropertySelect id={`${id}-prio`} name="priority" mono value={String(prio.value)} options={PRIORITY_OPTIONS} onChange={(v) => prio.change(Number(v) as Priority)} />
        </div>
        <div className="flex flex-col gap-1.5">
          <FieldLabel htmlFor={`${id}-importance`}>Importance</FieldLabel>
          <input
            id={`${id}-importance`}
            name="importance"
            type="number"
            min={0}
            max={100}
            value={importance.value}
            onChange={(e) => importance.change(e.target.value)}
            onBlur={importance.flush}
            className={`${BOX_INPUT} h-[34px] px-2.5 font-mono text-[13px] pointer-coarse:h-11`}
          />
        </div>
        {prio.failed && <div className="col-span-2"><SaveError what="priority" onRetry={prio.retry} /></div>}
        {importance.failed && <div className="col-span-2"><SaveError what="importance" onRetry={importance.retry} /></div>}
      </div>

      <div
        role="meter"
        aria-label="Importance"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={task.importance}
        className="h-[3px] flex-none overflow-hidden rounded-[2px] bg-line-2"
      >
        <span className="block h-full rounded-[2px] bg-fg-2 transition-[width] duration-[400ms] ease-bt" style={{ width: `${task.importance}%` }} />
      </div>

      <div className="flex flex-col gap-1.5">
        <FieldLabel htmlFor={`${id}-project`}>Project</FieldLabel>
        <PropertySelect id={`${id}-project`} name="project" value={project.value} options={projectOptions} onChange={project.change} />
        {project.failed && <SaveError what="project" onRetry={project.retry} />}
      </div>

      <div className="flex flex-col gap-[5px] border-t border-line pt-3 font-mono text-[10.5px] text-fg-3">
        <span>created {relativeTime(task.createdAt, now)}</span>
        <span>updated {relativeTime(task.updatedAt, now)}</span>
      </div>
    </aside>
  );
}
