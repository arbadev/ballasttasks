import { describe, expect, it } from "vitest";
import { InMemoryDirectoryService } from "./inMemoryDirectoryService";

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
});
