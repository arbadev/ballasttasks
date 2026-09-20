import { describe, expect, it } from "vitest";
import { parseTaskRoute, taskHref, returnDestination, changeTaskRoute } from "./route";

const id = "b334bf29-bf2e-400f-8e1a-9d5d47f10061";
describe("task URLs are the query authority", () => {
  it("round trips a project, scope, all filters, search, ordering, board and page", () => {
    const url = `/projects/${id}?scope=mine&status=testing&due=week&priority=1&q=hello+world&signal=soon&sort=due&view=board&offset=100`;
    const route = parseTaskRoute(url);
    expect(route).toMatchObject({ query: { project: id, scope: "mine", status: "testing", due: "week", priority: "1", search: "hello world", signal: "soon" }, sort: "due", view: "board", pageOffset: 100 });
    expect(parseTaskRoute(taskHref(route))).toEqual(route);
  });
  it("validates enums, bounded search and pagination; ignores duplicate/unknown parameters", () => {
    const route = parseTaskRoute("/tasks/mine?status=invalid&view=invalid&offset=-1&priority=1&priority=2&q=%00&token=secret");
    expect(taskHref(route)).toBe("/tasks/mine");
    expect(taskHref(parseTaskRoute("/tasks?offset=9007199254740992"))).toBe("/tasks");
  });
  it.each(["https://evil.test/tasks", "//evil.test/tasks", "/\\evil.test/tasks", "/login", "/auth/callback?code=x", "/tasks%2f..%2flogin", "/projects/not-a-uuid", "javascript:alert(1)"])("refuses unsafe return destination %s", (path) => {
    expect(returnDestination(path)).toBe("/tasks");
  });
  it("retains a valid protected return destination, but drops unknown query values", () => {
    expect(returnDestination(`/projects/${id}?view=board&q=hello&token=private`)).toBe(`/projects/${id}?q=hello&view=board`);
  });
  it("scope navigation leaves the selected project and filters only when explicitly retained in a project route", () => {
    const project = parseTaskRoute(`/projects/${id}?priority=1&offset=100`);
    const mine = changeTaskRoute(project, { type: "scopeSelected", scope: "mine" });
    expect(taskHref(mine!)).toBe("/tasks/mine?priority=1");
    expect(changeTaskRoute(project, { type: "searchChanged", search: "needle" })?.pageOffset).toBe(0);
  });
});
