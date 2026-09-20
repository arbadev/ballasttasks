import { act, fireEvent, render, screen } from "@testing-library/react";
import { Providers } from "@/app/providers";
import type { Task } from "@/features/tasks/model/types";
import { seedTasks } from "@/features/tasks/services/seed";
import { WorkspaceProvider, useWorkspace } from "@/features/tasks/workspace/WorkspaceProvider";
import { FakeDirectoryService, FakeTaskService } from "@/test/fakeServices";
import { NOW } from "@/test/tasks";
import { TaskDetail } from "../TaskDetail";
import { ScriptedStepGeneration } from "./ScriptedStepGeneration";

/** Stands in for the list: one button per task, so a test opens the panel the way a user does. */
function Openers() {
  const { state, actions } = useWorkspace();
  return (
    <ul aria-label="Openers">
      {state.tasks.map((t) => (
        <li key={t.id}>
          <button type="button" data-opener={t.id} onClick={() => actions.selectTask(t.id)}>
            open {t.id}
          </button>
        </li>
      ))}
    </ul>
  );
}

interface Options {
  tasks?: Task[];
  taskService?: FakeTaskService;
}

/** Renders the panel under the real composition root and workspace, with fakes behind them. */
export async function renderDetail(options: Options = {}) {
  const taskService = options.taskService ?? new FakeTaskService(options.tasks ?? seedTasks(NOW));
  const generation = new ScriptedStepGeneration(taskService);
  const view = render(
    <Providers taskService={taskService} directoryService={new FakeDirectoryService()} stepGenerationService={generation} clock={() => NOW}>
      <WorkspaceProvider>
        <Openers />
        <TaskDetail />
      </WorkspaceProvider>
    </Providers>,
  );
  await screen.findByRole("list", { name: "Openers" });
  await screen.findAllByText(/^open /);
  return { ...view, taskService, generation };
}

export const opener = (id: string) => screen.getByText(`open ${id}`);

/** Opens a task as a user would: focus its opener, then activate it. */
export function openTask(id: string) {
  opener(id).focus();
  fireEvent.click(opener(id));
  return screen.getByRole("dialog");
}

/** Lets every pending promise (a save, a command) settle inside act. */
export async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}
