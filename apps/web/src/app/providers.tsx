"use client";

import { createContext, useContext, useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";
import { HttpAuthService } from "@/features/auth/service";
import type { AuthService, Session } from "@/features/auth/types";
import { HttpTaskService } from "@/features/tasks/services/httpTaskService";
import { HttpDirectoryService } from "@/features/tasks/services/httpDirectoryService";
import { HttpStepGenerationService } from "@/features/tasks/services/httpStepGenerationService";
import { HttpHealthService, type HealthService } from "@/features/health/service";
import { InMemoryDirectoryService } from "@/features/tasks/services/inMemoryDirectoryService";
import { InMemoryStepGenerationService } from "@/features/tasks/services/inMemoryStepGenerationService";
import { InMemoryTaskService } from "@/features/tasks/services/inMemoryTaskService";
import { InMemoryTaskStore } from "@/features/tasks/services/inMemoryTaskStore";
import { systemClock, type Clock, type DirectoryService, type StepGenerationService, type TaskService } from "@/features/tasks/services/types";
import { ApiClient } from "@/lib/api/client";
import { config } from "@/lib/config";

interface Services {
  auth: AuthService | null;
  session: Session;
  health: HealthService;
  tasks: TaskService;
  directory: DirectoryService;
  stepGeneration: StepGenerationService;
  clock: Clock;
}

const ServicesContext = createContext<Services | null>(null);
const ANONYMOUS: Session = { epoch: 0, user: null };
const emptySession = () => ANONYMOUS;
const emptySubscribe = () => () => {};

interface ProvidersProps {
  children: ReactNode;
  /** Explicit offline mode, never a fallback for an HTTP failure. */
  demo?: boolean;
  authService?: AuthService | null;
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
 * HTTP is the default. Authentication and all data services are memory-only and session-scoped.
 */
export function Providers({ children, demo = config.serviceMode === "demo", authService, healthService, taskService, directoryService, stepGenerationService, clock }: ProvidersProps) {
  const auth = useMemo(() => {
    if (authService !== undefined) return authService;
    if (demo || taskService) return null;
    const client: ApiClient = new ApiClient(config.apiUrl, {
      token: () => service.token(), version: () => service.current().epoch, unauthorized: () => service.expire(),
    });
    const service = new HttpAuthService(client, config.apiUrl);
    return service;
  }, [authService, demo, taskService]);
  const session = useSyncExternalStore(auth?.subscribe ?? emptySubscribe, auth?.current ?? emptySession, emptySession);
  const epoch = session.epoch;
  const implementations = useMemo<Omit<Services, "auth" | "session">>(() => {
    const now = clock ?? systemClock;
    const client = new ApiClient(config.apiUrl, auth instanceof HttpAuthService ? {
      token: auth.token, version: () => auth.current().epoch, expectedVersion: epoch, unauthorized: auth.expire,
    } : undefined);
    const store = demo ? new InMemoryTaskStore(now) : null;
    const httpTasks = new HttpTaskService(client);
    return {
      health: healthService ?? new HttpHealthService(new ApiClient(config.apiUrl)),
      tasks: taskService ?? (store ? new InMemoryTaskService(store) : httpTasks),
      directory: directoryService ?? (demo ? new InMemoryDirectoryService() : new HttpDirectoryService(client)),
      stepGeneration: stepGenerationService ?? (store ? new InMemoryStepGenerationService(store) : new HttpStepGenerationService(client, httpTasks, now)),
      clock: now,
    };
  }, [auth, epoch, demo, healthService, taskService, directoryService, stepGenerationService, clock]);
  useEffect(() => () => implementations.stepGeneration.dispose?.(), [implementations]);
  const services: Services = { ...implementations, auth, session };

  return <ServicesContext.Provider value={services}>{children}</ServicesContext.Provider>;
}

function useServices(hook: string): Services {
  const services = useContext(ServicesContext);
  if (!services) {
    throw new Error(`${hook} must be used inside <Providers>.`);
  }
  return services;
}

export function useAuthService(): AuthService | null {
  return useServices("useAuthService").auth;
}

export function useSession(): Session {
  return useServices("useSession").session;
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
