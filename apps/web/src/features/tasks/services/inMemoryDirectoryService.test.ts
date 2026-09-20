import { describe, expect, it, vi } from "vitest";
import { InMemoryDirectoryService } from "./inMemoryDirectoryService";
import { ProjectRejectedError } from "./types";

describe("InMemoryDirectoryService", () => {
  const service = new InMemoryDirectoryService();

  it("lists the people, including the assistant", async () => {
    expect((await service.people()).map((p) => p.id)).toEqual(["ab", "lm", "tr", "ai"]);
  });

  it("lists the projects", async () => {
    expect((await service.projects()).map((p) => p.name)).toEqual(["Ballast Tasks", "Inbox"]);
  });

  it("knows the current user", async () => {
    expect(await service.currentUser()).toMatchObject({ id: "ab", name: "Andres Barradas", role: "owner" });
  });

  it("hands out copies", async () => {
    (await service.people()).pop();
    expect(await service.people()).toHaveLength(4);
  });

  it("gives the seeded projects their task keys", async () => {
    expect((await service.projects()).map((p) => p.key)).toEqual(["BT", "IN"]);
  });
});

describe("InMemoryDirectoryService.updateProject", () => {
  it("preserves identity/key, normalizes metadata and persists canonical reads", async () => {
    const service = new InMemoryDirectoryService({ latencyMs: 0 });
    const [project] = await service.projects();
    const saved = await service.updateProject(project.id, { name: "  Renamed   project  ", tone: "info", key: "BAD" } as never);
    expect(saved).toEqual({ ...project, name: "Renamed project", tone: "info" });
    expect((await service.projects())[0]).toEqual(saved);
    await expect(service.updateProject(project.id, { name: "", tone: "info" })).rejects.toBeInstanceOf(ProjectRejectedError);
    await expect(service.updateProject("missing", { name: "Valid", tone: "info" })).rejects.toThrow("Project not found");
    expect((await service.projects())[0]).toEqual(saved);
  });
  it("applies only the fields the edit carries, without judging a name it was not given", async () => {
    const service = new InMemoryDirectoryService({ latencyMs: 0 });
    const [project, other] = await service.projects();
    const recoloured = await service.updateProject(project.id, { tone: "warn" });
    expect(recoloured).toEqual({ ...project, tone: "warn" });
    const renamed = await service.updateProject(project.id, { name: "Only the name" });
    expect(renamed).toEqual({ ...project, name: "Only the name", tone: "warn" });
    await expect(service.updateProject(project.id, { name: other.name })).rejects.toBeInstanceOf(ProjectRejectedError);
    expect((await service.projects())[0]).toEqual(renamed);
  });
});

describe("InMemoryDirectoryService.createProject", () => {
  const create = () => new InMemoryDirectoryService({ latencyMs: 0 });

  it("stores the project with a new id and lists it after the seeded ones", async () => {
    const service = create();
    const project = await service.createProject({ name: "Marketing", key: "MKT", tone: "info" });
    expect(project).toEqual({ id: "p1", name: "Marketing", key: "MKT", tone: "info" });
    expect((await service.projects()).map((p) => p.id)).toEqual(["ballast", "inbox", "p1"]);
    expect((await service.createProject({ name: "Ops", key: "OPS", tone: "ok" })).id).toBe("p2");
  });

  it("trims the name before storing it", async () => {
    expect((await create().createProject({ name: "  Release   notes ", key: "RN", tone: "warn" })).name).toBe("Release notes");
  });

  it("rejects a duplicate name or key with the field errors, and stores nothing", async () => {
    const service = create();
    const attempt = service.createProject({ name: "ballast tasks", key: "BT", tone: "info" });
    await expect(attempt).rejects.toBeInstanceOf(ProjectRejectedError);
    await expect(attempt).rejects.toMatchObject({
      errors: { name: 'A project named "Ballast Tasks" already exists.', key: "The key BT is already used by Ballast Tasks." },
    });
    expect(await service.projects()).toHaveLength(2);
  });

  it("rejects a malformed key", async () => {
    await expect(create().createProject({ name: "Marketing", key: "mkt1", tone: "info" })).rejects.toMatchObject({ errors: { key: "Use 2 to 4 letters." } });
  });

  it("keeps each service's projects to itself", async () => {
    await create().createProject({ name: "Marketing", key: "MKT", tone: "info" });
    expect(await create().projects()).toHaveLength(2);
  });

  it("answers after its latency, like a backend would", async () => {
    vi.useFakeTimers();
    try {
      let settled = false;
      const pending = new InMemoryDirectoryService({ latencyMs: 300 }).createProject({ name: "Marketing", key: "MKT", tone: "info" }).then(() => (settled = true));
      await vi.advanceTimersByTimeAsync(299);
      expect(settled).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      await pending;
      expect(settled).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});
