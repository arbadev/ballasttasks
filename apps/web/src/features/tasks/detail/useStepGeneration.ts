"use client";

import { useCallback, useSyncExternalStore } from "react";
import { useStepGenerationService, useTaskService } from "@/app/providers";
import type { Generation } from "../services/types";
import { useTaskCommands } from "../workspace/WorkspaceProvider";
import { useDetailSession } from "./DetailSession";

export interface StepGenerationView {
  /** The generation in flight, when it belongs to this task. */
  generation: Generation | null;
  failed: boolean;
  start(): void;
  removeProposed(stepId: string): void;
  accept(): void;
  discard(): void;
}

/**
 * The step generation as one task sees it. The service holds the generation and the session
 * holds a failed start, so both survive the panel closing and another task being opened.
 */
export function useStepGeneration(taskId: string): StepGenerationView {
  const service = useStepGenerationService();
  const tasks = useTaskService();
  const commands = useTaskCommands();
  const { track, generationFailed, setGenerationFailed } = useDetailSession();

  const subscribe = useCallback((listener: () => void) => service.subscribe(listener), [service]);
  const current = useSyncExternalStore(subscribe, () => service.current(), () => null);

  return {
    generation: current?.taskId === taskId ? current : null,
    failed: generationFailed(taskId),
    start: () => {
      setGenerationFailed(taskId, false);
      service.start(taskId).catch(() => setGenerationFailed(taskId, true));
    },
    removeProposed: (stepId) => service.removeProposed(stepId),
    accept: () => {
      void track(service.accept())
        .then((task) => task && commands.sync(task))
        .catch(() => {});
    },
    discard: () => {
      // Discarding resolves to nothing, but it is logged on the task: read the task back.
      void track(service.discard().then(() => tasks.get(taskId)))
        .then((task) => task && commands.sync(task))
        .catch(() => {});
    },
  };
}
