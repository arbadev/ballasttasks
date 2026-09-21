import { act, fireEvent, screen } from "@testing-library/react";
import { useMemo, useState } from "react";
import { describe, expect, it } from "vitest";
import { renderWithServices } from "@/test/renderWithServices";
import { TaskRouteContext } from "../workspace/TaskRouteContext";
import { WorkspaceProvider } from "../workspace/WorkspaceProvider";
import { parseTaskRoute, type TaskRoute } from "../workspace/route";
import { FilterToolbar } from "./FilterToolbar";

/**
 * Controlled timing: the test decides when each written URL reaches the route, as Next's
 * transition does, and when the user navigates (Back/Forward) instead.
 */
function renderToolbar(href = "/tasks") {
  const written: string[] = [];
  const controls = {} as { deliver(search: string): void; navigateBack(search: string): void };
  function Harness() {
    const [route, setRoute] = useState(() => parseTaskRoute(href, true));
    const [resets, setResets] = useState(0);
    const at = (search: string): TaskRoute => ({ ...route, query: { ...route.query, search } });
    controls.deliver = (search) => act(() => setRoute(at(search)));
    controls.navigateBack = (search) => act(() => { setResets((n) => n + 1); setRoute(at(search)); });
    const navigation = useMemo(() => ({
      route,
      resets,
      navigate: (next: TaskRoute, replace?: boolean) => {
        written.push(`${next.query.search}${replace ? " (replace)" : ""}`);
        if (!replace) setResets((n) => n + 1);
      },
    }), [route, resets]);
    return <TaskRouteContext.Provider value={navigation}><WorkspaceProvider><FilterToolbar /></WorkspaceProvider></TaskRouteContext.Provider>;
  }
  renderWithServices(<Harness />);
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
