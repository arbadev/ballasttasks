"use client";

import { createContext, useContext } from "react";
import type { TaskRoute } from "./route";

export interface TaskNavigation {
  route: TaskRoute;
  navigate(route: TaskRoute, replace?: boolean): void;
}
export const TaskRouteContext = createContext<TaskNavigation | null>(null);
export const useTaskNavigation = () => useContext(TaskRouteContext);
