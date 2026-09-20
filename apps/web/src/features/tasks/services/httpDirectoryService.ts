import { ApiError, type HttpTransport } from "@/lib/api/client";
import type { DirectoryService, NewProject, ProjectEdit } from "./types";
import { ProjectRejectedError } from "./types";
import { personFromApi, projectFromApi, type Schemas } from "./httpMapping";

export class HttpDirectoryService implements DirectoryService {
  constructor(private readonly client: HttpTransport) {}
  async people() { return (await this.client.get<Schemas["PeopleResponse"]>("/users")).items.map(personFromApi); }
  async projects() { return (await this.client.get<Schemas["ProjectListResponse"]>("/projects")).items.map(projectFromApi); }
  async currentUser() { return personFromApi(await this.client.get<Schemas["UserResponse"]>("/auth/me")); }
  async updateProject(id: string, input: ProjectEdit) {
    // A partial update: a colour the palette cannot show is only rewritten when it was chosen again.
    const body: Schemas["ProjectUpdate"] = {};
    if (input.name !== undefined) body.name = input.name;
    if (input.tone !== undefined) body.color = input.tone === "accent" ? "acc" : input.tone;
    try {
      return projectFromApi(await this.client.request<Schemas["ProjectResponse"]>(`/projects/${encodeURIComponent(id)}`, {
        method: "PATCH", body,
      }));
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) throw new ProjectRejectedError({ name: "Check the project name and colour." });
      throw error;
    }
  }
  async createProject(input: NewProject) {
    try {
      return projectFromApi(await this.client.request<Schemas["ProjectResponse"]>("/projects", {
        method: "POST", body: { name: input.name, key: input.key, color: input.tone === "accent" ? "acc" : input.tone },
      }));
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) throw new ProjectRejectedError({ key: "That key is already in use." });
      if (error instanceof ApiError && error.status === 422) throw new ProjectRejectedError({ name: "Check the project name.", key: "Use 2–5 uppercase letters." });
      throw error;
    }
  }
}
