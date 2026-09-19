"use client";

import { useCallback, useState } from "react";
import { useDirectoryService } from "@/app/providers";
import type { Project } from "@/features/tasks/model/types";
import { ProjectRejectedError, type NewProject, type ProjectFieldErrors } from "@/features/tasks/services/types";
import { useWorkspace } from "@/features/tasks/workspace/WorkspaceProvider";

export type CreateProjectState = { status: "idle" } | { status: "pending" } | { status: "failed"; message: string };

export type CreateProjectResult =
  | { created: true; project: Project }
  /** `errors` when the directory refused a field; absent when the request itself failed. */
  | { created: false; errors?: ProjectFieldErrors };

/**
 * Creates a project through DirectoryService and, once it is stored, hands it to the
 * workspace, which lists it in the sidebar and selects it.
 */
export function useCreateProject(): { state: CreateProjectState; create: (input: NewProject) => Promise<CreateProjectResult> } {
  const directory = useDirectoryService();
  const { actions } = useWorkspace();
  const [state, setState] = useState<CreateProjectState>({ status: "idle" });

  const create = useCallback(
    async (input: NewProject): Promise<CreateProjectResult> => {
      setState({ status: "pending" });
      try {
        const project = await directory.createProject(input);
        actions.addProject(project);
        setState({ status: "idle" });
        return { created: true, project };
      } catch (error) {
        if (error instanceof ProjectRejectedError) {
          setState({ status: "idle" });
          return { created: false, errors: error.errors };
        }
        setState({ status: "failed", message: error instanceof Error ? error.message : "Try again in a moment." });
        return { created: false };
      }
    },
    [directory, actions],
  );

  return { state, create };
}
