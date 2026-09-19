import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { Providers } from "@/app/providers";
import { FakeDirectoryService, FakeStepGenerationService, FakeTaskService } from "./fakeServices";
import { NOW } from "./tasks";
import type { Task } from "@/features/tasks/model/types";
import { seedTasks } from "@/features/tasks/services/seed";

/** Renders `ui` under the composition root with fake services, the design's seed and a fixed clock. */
export function renderWithServices(ui: ReactElement, options: { tasks?: Task[]; taskService?: FakeTaskService } = {}) {
  const taskService = options.taskService ?? new FakeTaskService(options.tasks ?? seedTasks(NOW));
  const view = render(
    <Providers taskService={taskService} directoryService={new FakeDirectoryService()} stepGenerationService={new FakeStepGenerationService()} clock={() => NOW}>
      {ui}
    </Providers>,
  );
  return { ...view, taskService };
}
