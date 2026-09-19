"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { HttpHealthService, type HealthService } from "@/features/health/service";
import { InMemoryDirectoryService } from "@/features/tasks/services/inMemoryDirectoryService";
import { InMemoryStepGenerationService } from "@/features/tasks/services/inMemoryStepGenerationService";
import { InMemoryTaskService } from "@/features/tasks/services/inMemoryTaskService";
import { InMemoryTaskStore } from "@/features/tasks/services/inMemoryTaskStore";
import { systemClock, type Clock, type DirectoryService, type StepGenerationService, type TaskService } from "@/features/tasks/services/types";
import { ApiClient } from "@/lib/api/client";
import { config } from "@/lib/config";

interface Services {
  health: HealthService;
  tasks: TaskService;
  directory: DirectoryService;
  stepGeneration: StepGenerationService;
  clock: Clock;
}

const ServicesContext = createContext<Services | null>(null);

interface ProvidersProps {
  children: ReactNode;
  /** Each override replaces the default implementation; tests pass fakes here. */
  healthService?: HealthService;
  taskService?: TaskService;
  directoryService?: DirectoryService;
  stepGenerationService?: StepGenerationService;
  clock?: Clock;
}

/**
 * Composition root of the frontend: the only place concrete services are constructed.
 * Everything below depends on the service interfaces through the hooks in this file.
 * The task services are in-memory until the HTTP-backed ones exist; swapping them is a
 * change to this file alone.
 */
export function Providers({ children, healthService, taskService, directoryService, stepGenerationService, clock }: ProvidersProps) {
  const services = useMemo<Services>(() => {
    const now = clock ?? systemClock;
    // One store behind both task-facing services, so accepted steps show up in the task.
    const store = new InMemoryTaskStore(now);
    return {
      health: healthService ?? new HttpHealthService(new ApiClient(config.apiUrl)),
      tasks: taskService ?? new InMemoryTaskService(store),
      directory: directoryService ?? new InMemoryDirectoryService(),
      stepGeneration: stepGenerationService ?? new InMemoryStepGenerationService(store),
      clock: now,
    };
  }, [healthService, taskService, directoryService, stepGenerationService, clock]);

  return <ServicesContext.Provider value={services}>{children}</ServicesContext.Provider>;
}

function useServices(hook: string): Services {
  const services = useContext(ServicesContext);
  if (!services) {
    throw new Error(`${hook} must be used inside <Providers>.`);
  }
  return services;
}

export function useHealthService(): HealthService {
  return useServices("useHealthService").health;
}

export function useTaskService(): TaskService {
  return useServices("useTaskService").tasks;
}

export function useDirectoryService(): DirectoryService {
  return useServices("useDirectoryService").directory;
}

export function useStepGenerationService(): StepGenerationService {
  return useServices("useStepGenerationService").stepGeneration;
}

export function useClock(): Clock {
  return useServices("useClock").clock;
}
