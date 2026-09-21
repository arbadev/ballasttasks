import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { useCallback, useMemo, useState } from "react";
import { describe, expect, it } from "vitest";
import { renderWithServices } from "@/test/renderWithServices";
import { FakeQueryTaskService } from "@/test/fakeServices";
import { TaskRouteContext } from "../workspace/TaskRouteContext";
import { WorkspaceProvider } from "../workspace/WorkspaceProvider";
import { parseTaskRoute, type TaskRoute } from "../workspace/route";
import { FilterToolbar } from "./FilterToolbar";
import type { TaskPageRequest } from "../services/query";
import { seedTasks } from "../services/seed";
import { NOW } from "@/test/tasks";

/**
 * Controlled timing: the test decides when each written URL reaches the route, as Next's
 * transition does, and when the user navigates (Back/Forward) instead.
 */
function renderToolbar(href = "/tasks", taskService?: FakeQueryTaskService) {
  const written: string[] = [];
  const controls = {} as { deliver(search: string): void; navigateBack(search: string): void; reset(): void; deliverRoute(href: string): void };
  function Harness() {
    const [route, setRoute] = useState(() => parseTaskRoute(href, true));
    const [resets, setResets] = useState(0);
    const at = (search: string): TaskRoute => ({ ...route, query: { ...route.query, search } });
    controls.deliver = (search) => act(() => setRoute(at(search)));
    controls.navigateBack = (search) => act(() => { setResets((n) => n + 1); setRoute(at(search)); });
    controls.reset = () => act(() => setResets((n) => n + 1));
    controls.deliverRoute = (next) => act(() => setRoute(parseTaskRoute(next, true)));
    const navigate = useCallback((next: TaskRoute, replace?: boolean) => {
      written.push(`${next.query.search}${replace ? " (replace)" : ""}`);
      if (!replace) setResets((n) => n + 1);
    }, []);
    const navigation = useMemo(() => ({ route, resets, navigate }), [route, resets, navigate]);
    return <TaskRouteContext.Provider value={navigation}><WorkspaceProvider><FilterToolbar /></WorkspaceProvider></TaskRouteContext.Provider>;
  }
  renderWithServices(<Harness />, { taskService });
  const box = screen.getByRole("searchbox", { name: "Search tasks" }) as HTMLInputElement;
  const type = (value: string) => fireEvent.change(box, { target: { value } });
  return { box, type, written, controls };
}

describe("search box against delayed route projections (controlled timing)", () => {
  it("starts from the route's canonical search", () => {
    expect(renderToolbar("/tasks?q=prd").box).toHaveValue("prd");
  });

  it("keeps the newest typed text while older URLs it wrote arrive one at a time", () => {
    const { box, type, written, controls } = renderToolbar();
    type("a");
    type("");
    type("b");
    expect(written).toEqual(["a (replace)", " (replace)", "b (replace)"]);
    for (const search of ["a", "", "b"]) {
      controls.deliver(search);
      expect(box).toHaveValue("b");
    }
  });

  it("keeps a retyped search while the pending edits settle on the committed one", () => {
    const { box, type, controls } = renderToolbar("/tasks?q=prd");
    for (const value of ["", "p", "pr", "prd", "prdx"]) type(value);
    for (const search of ["", "p", "pr", "prd"]) {
      controls.deliver(search);
      expect(box).toHaveValue("prdx");
    }
    controls.deliver("prdx");
    expect(box).toHaveValue("prdx");
  });

  it("follows Back/Forward even to a search typed before", () => {
    const { box, type, controls } = renderToolbar("/tasks?q=prd");
    type("");
    type("prd");
    controls.deliver("prd");
    controls.navigateBack("");
    expect(box).toHaveValue("");
    controls.navigateBack("prd");
    expect(box).toHaveValue("prd");
    type("prdx");
    controls.navigateBack("pr");
    expect(box).toHaveValue("pr");
  });

  it("shows the route's search after a pushed navigation made mid-edit", () => {
    const { box, type, written } = renderToolbar();
    type("prd");
    fireEvent.change(screen.getByRole("combobox", { name: "Due" }), { target: { value: "overdue" } });
    expect(written.at(-1)).toBe("");
    expect(box).toHaveValue("");
  });

  it("empties the box for a search the route refuses", () => {
    const { box, type, written } = renderToolbar();
    type("a\tb");
    expect(box).toHaveValue("");
    expect(written).toEqual([" (replace)"]);
  });
});

describe("task queries against the navigation reset signal (controlled timing)", () => {
  const settle = (ms: number) => act(() => new Promise((resolve) => setTimeout(resolve, ms)));
  const queries = (service: FakeQueryTaskService) => service.calls.filter(([name]) => name === "query").map(([, request]) => request as TaskPageRequest);

  it("starts no query when only the reset signal changes, and queries when the route does", async () => {
    const service = new FakeQueryTaskService(seedTasks(NOW));
    const { controls } = renderToolbar("/tasks", service);
    await waitFor(() => expect(queries(service)).toHaveLength(1));
    controls.reset();
    await settle(50);
    expect(queries(service)).toHaveLength(1);
    controls.deliverRoute("/tasks?due=overdue");
    await waitFor(() => expect(queries(service)).toHaveLength(2));
    expect(queries(service)[1].query.due).toBe("overdue");
  });

  it("does not restart a pending search debounce when Back/Forward's reset arrives before its route", async () => {
    const service = new FakeQueryTaskService(seedTasks(NOW));
    const { controls } = renderToolbar("/tasks", service);
    await waitFor(() => expect(queries(service)).toHaveLength(1));
    controls.deliverRoute("/tasks?q=prd");
    await settle(150);
    controls.reset();
    await settle(170);
    expect(queries(service).map((request) => request.query.search)).toEqual(["", "prd"]);
  });
});
