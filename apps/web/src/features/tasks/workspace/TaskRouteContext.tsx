"use client";

import { createContext, useContext } from "react";
import type { TaskRoute } from "./route";

export interface TaskNavigation {
  route: TaskRoute;
  /** Counts the navigations the user asked for (Back/Forward and pushed changes), not the URL edits typing writes. */
  resets: number;
  navigate(route: TaskRoute, replace?: boolean): void;
}
export const TaskRouteContext = createContext<TaskNavigation | null>(null);
export const useTaskNavigation = () => useContext(TaskRouteContext);
