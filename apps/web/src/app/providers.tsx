"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { HttpHealthService, type HealthService } from "@/features/health/service";
import { ApiClient } from "@/lib/api/client";
import { config } from "@/lib/config";

const HealthServiceContext = createContext<HealthService | null>(null);

interface ProvidersProps {
  children: ReactNode;
  /** Overrides the HTTP-backed service; tests pass a fake here. */
  healthService?: HealthService;
}

/**
 * Composition root of the frontend: the only place concrete services are constructed.
 * Everything below depends on the HealthService interface through useHealthService().
 */
export function Providers({ children, healthService }: ProvidersProps) {
  const service = useMemo(
    () => healthService ?? new HttpHealthService(new ApiClient(config.apiUrl)),
    [healthService],
  );

  return <HealthServiceContext.Provider value={service}>{children}</HealthServiceContext.Provider>;
}

export function useHealthService(): HealthService {
  const service = useContext(HealthServiceContext);
  if (!service) {
    throw new Error("useHealthService must be used inside <Providers>.");
  }
  return service;
}
