import { normalizeName, validateProject, validateProjectName } from "@/features/projects/model/rules";
import type { Person, Project } from "../model/types";
import { CURRENT_USER_ID, SEED_PEOPLE, SEED_PROJECTS } from "./seed";
import { ProjectRejectedError, type DirectoryService, type NewProject, type ProjectEdit } from "./types";

/** How long creating a project takes, so the pending state is seen as it will be over HTTP. */
export const CREATE_PROJECT_DELAY_MS = 450;

export class InMemoryDirectoryService implements DirectoryService {
  private allProjects: Project[] = [...SEED_PROJECTS];
  private sequence = 0;
  private readonly latencyMs: number;

  constructor(options: { latencyMs?: number } = {}) {
    this.latencyMs = options.latencyMs ?? CREATE_PROJECT_DELAY_MS;
  }

  async people(): Promise<Person[]> {
    return [...SEED_PEOPLE];
  }

  async projects(): Promise<Project[]> {
    return [...this.allProjects];
  }

  async currentUser(): Promise<Person> {
    return SEED_PEOPLE.find((p) => p.id === CURRENT_USER_ID)!;
  }

  async updateProject(id: string, input: ProjectEdit): Promise<Project> {
    if (this.latencyMs > 0) await new Promise((resolve) => setTimeout(resolve, this.latencyMs));
    const existing = this.allProjects.find((project) => project.id === id);
    if (!existing) throw new Error("Project not found.");
    const saved = { ...existing };
    if (input.name !== undefined) {
      const name = validateProjectName(input.name, this.allProjects.filter((project) => project.id !== id));
      if (name) throw new ProjectRejectedError({ name });
      saved.name = normalizeName(input.name);
    }
    if (input.tone !== undefined) saved.tone = input.tone;
    this.allProjects = this.allProjects.map((project) => project.id === id ? saved : project);
    return saved;
  }

  async createProject(input: NewProject): Promise<Project> {
    if (this.latencyMs > 0) await new Promise((resolve) => setTimeout(resolve, this.latencyMs));
    // Checked here as well as in the form: the directory, not the UI, owns uniqueness.
    const errors = validateProject(input, this.allProjects);
    if (Object.keys(errors).length > 0) throw new ProjectRejectedError(errors);

    const project: Project = { id: `p${++this.sequence}`, name: normalizeName(input.name), key: input.key, tone: input.tone };
    this.allProjects = [...this.allProjects, project];
    return project;
  }
}
