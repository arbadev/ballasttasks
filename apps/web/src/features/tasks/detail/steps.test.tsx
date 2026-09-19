import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { openTask, renderDetail, settle } from "./testing/renderDetail";

const steps = () => within(screen.getByRole("region", { name: "Steps" }));
const stepTexts = () => within(steps().getByRole("list", { name: "Steps" })).getAllByRole("listitem").map((li) => li.textContent);
const DRAFT = ["users table + Alembic migration", "Ports: PasswordHasher and TokenIssuer", "Use cases: register, login"];

describe("steps checklist", () => {
  it("lists the steps with their progress", async () => {
    await renderDetail();
    openTask("t1");
    expect(stepTexts()).toHaveLength(6);
    expect(steps().getByText("3/6")).toBeInTheDocument();
    const bar = steps().getByRole("progressbar", { name: "Steps completed" });
    expect(bar).toHaveAttribute("aria-valuenow", "50");
    expect(steps().getByRole("checkbox", { name: "Task entity and TaskStatus enum in domain" })).toBeChecked();
    expect(steps().getByRole("checkbox", { name: "Alembic migration for the tasks table" })).not.toBeChecked();
  });

  it("says none yet for a task without steps", async () => {
    await renderDetail();
    openTask("t4");
    expect(steps().getByText("none yet")).toBeInTheDocument();
    expect(steps().getByRole("progressbar", { name: "Steps completed" })).toHaveAttribute("aria-valuenow", "0");
    expect(steps().queryByRole("list", { name: "Steps" })).not.toBeInTheDocument();
  });

  it("toggles a step and moves the progress", async () => {
    const { taskService } = await renderDetail();
    openTask("t1");
    fireEvent.click(steps().getByRole("checkbox", { name: "Alembic migration for the tasks table" }));
    await settle();
    expect(taskService.calls.filter((c) => c[0] === "toggleStep")).toHaveLength(1);
    expect(steps().getByRole("checkbox", { name: "Alembic migration for the tasks table" })).toBeChecked();
    expect(steps().getByText("4/6")).toBeInTheDocument();
  });

  it("removes a step", async () => {
    const { taskService } = await renderDetail();
    openTask("t1");
    fireEvent.click(steps().getByRole("button", { name: "Remove step: Alembic migration for the tasks table" }));
    await settle();
    expect(taskService.calls.filter((c) => c[0] === "removeStep")).toHaveLength(1);
    expect(stepTexts()).toHaveLength(5);
    expect(steps().getByText("3/5")).toBeInTheDocument();
  });

  it("adds a step on Enter, clears the input, and ignores a blank one", async () => {
    const { taskService } = await renderDetail();
    openTask("t4");
    const input = steps().getByRole("textbox", { name: "Add a step" });
    expect(input).toHaveAttribute("placeholder", "Add a step and press Enter");

    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });
    await settle();
    expect(taskService.calls.filter((c) => c[0] === "addStep")).toEqual([]);

    fireEvent.change(input, { target: { value: "  Pick the token lifetime " } });
    fireEvent.keyDown(input, { key: "Enter" });
    await settle();
    expect(taskService.calls).toContainEqual(["addStep", "t4", "Pick the token lifetime"]);
    expect(input).toHaveValue("");
    expect(stepTexts()).toEqual(["Pick the token lifetime"]);
    expect(steps().getByText("0/1")).toBeInTheDocument();
  });

  it("keeps a half-typed step when the panel closes and reopens", async () => {
    await renderDetail();
    openTask("t4");
    fireEvent.change(steps().getByRole("textbox", { name: "Add a step" }), { target: { value: "half typed" } });
    fireEvent.keyDown(window, { key: "Escape" });
    openTask("t4");
    expect(steps().getByRole("textbox", { name: "Add a step" })).toHaveValue("half typed");
  });
});

describe("step generation", () => {
  it("Generate steps starts a generation and shows the drafting state", async () => {
    const { generation } = await renderDetail();
    openTask("t1");
    fireEvent.click(steps().getByRole("button", { name: "Generate steps" }));
    await settle();

    expect(generation.calls).toEqual([["start", "t1"]]);
    const running = steps().getByRole("status", { name: "Drafting steps" });
    expect(running).toHaveTextContent("Drafting steps");
    expect(running).toHaveTextContent("reading the title, description and 2 attachments");
    expect(running).toHaveTextContent("background job · keep editing, the draft lands here");
    expect(steps().getByRole("button", { name: "Generate steps" })).toBeDisabled();
  });

  it("counts a single attachment in the singular", async () => {
    await renderDetail();
    openTask("t3");
    fireEvent.click(steps().getByRole("button", { name: "Generate steps" }));
    await settle();
    expect(steps().getByRole("status", { name: "Drafting steps" })).toHaveTextContent("and 1 attachment");
  });

  it("shows the proposal, lets steps be removed one by one, and adds what is left", async () => {
    const { generation } = await renderDetail();
    openTask("t4");
    fireEvent.click(steps().getByRole("button", { name: "Generate steps" }));
    await settle();
    generation.propose(DRAFT);
    await settle();

    const proposal = within(steps().getByRole("group", { name: "Proposed steps" }));
    expect(proposal.getByText("Assistant drafted 3 steps")).toBeInTheDocument();
    expect(proposal.getByText("proposed")).toBeInTheDocument();
    expect(proposal.getByText(/nothing is added until you say so/)).toBeInTheDocument();
    expect(steps().getByRole("button", { name: "Generate steps" })).toBeEnabled();

    fireEvent.click(proposal.getByRole("button", { name: `Remove proposed step: ${DRAFT[1]}` }));
    await settle();
    expect(generation.calls).toContainEqual(["removeProposed", "p2"]);
    expect(proposal.getByText("Assistant drafted 2 steps")).toBeInTheDocument();

    fireEvent.click(proposal.getByRole("button", { name: "Add 2 steps" }));
    await settle();
    expect(generation.calls).toContainEqual(["accept"]);
    expect(steps().queryByRole("group", { name: "Proposed steps" })).not.toBeInTheDocument();
    expect(stepTexts()).toEqual([DRAFT[0], DRAFT[2]]);
    expect(steps().getByText("0/2")).toBeInTheDocument();
  });

  it("uses the singular for a one-step proposal", async () => {
    const { generation } = await renderDetail();
    openTask("t4");
    fireEvent.click(steps().getByRole("button", { name: "Generate steps" }));
    await settle();
    generation.propose(["Only one"]);
    await settle();
    expect(steps().getByText("Assistant drafted 1 step")).toBeInTheDocument();
    expect(steps().getByRole("button", { name: "Add 1 step" })).toBeInTheDocument();
  });

  it("Discard drops the proposal and Regenerate starts over", async () => {
    const { generation } = await renderDetail();
    openTask("t4");
    fireEvent.click(steps().getByRole("button", { name: "Generate steps" }));
    await settle();
    generation.propose(DRAFT);
    await settle();

    fireEvent.click(steps().getByRole("button", { name: "Regenerate" }));
    await settle();
    expect(generation.calls.filter((c) => c[0] === "start")).toHaveLength(2);
    expect(steps().getByRole("status", { name: "Drafting steps" })).toBeInTheDocument();

    generation.propose(DRAFT);
    await settle();
    fireEvent.click(steps().getByRole("button", { name: "Discard" }));
    await settle();
    expect(generation.calls).toContainEqual(["discard"]);
    expect(steps().queryByRole("group", { name: "Proposed steps" })).not.toBeInTheDocument();
    expect(steps().queryByRole("list", { name: "Steps" })).not.toBeInTheDocument();
  });

  it("belongs to its task: hidden on another task, still there on the way back", async () => {
    const { generation } = await renderDetail();
    openTask("t4");
    fireEvent.click(steps().getByRole("button", { name: "Generate steps" }));
    await settle();

    fireEvent.keyDown(window, { key: "Escape" });
    openTask("t6");
    expect(steps().queryByRole("status", { name: "Drafting steps" })).not.toBeInTheDocument();
    expect(steps().getByRole("button", { name: "Generate steps" })).toBeEnabled();

    // The draft lands while the user is elsewhere.
    generation.propose(DRAFT);
    await settle();
    expect(steps().queryByRole("group", { name: "Proposed steps" })).not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    openTask("t4");
    expect(steps().getByRole("group", { name: "Proposed steps" })).toBeInTheDocument();
  });

  it("a failed generation says so and Retry starts it again; the failure stays with its task", async () => {
    const { generation } = await renderDetail();
    generation.failNextStart();
    openTask("t4");
    fireEvent.click(steps().getByRole("button", { name: "Generate steps" }));
    await settle();

    const failure = steps().getByRole("alert");
    expect(failure).toHaveTextContent("Could not draft steps. Nothing was changed.");

    fireEvent.keyDown(window, { key: "Escape" });
    openTask("t6");
    expect(steps().queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    openTask("t4");

    fireEvent.click(within(steps().getByRole("alert")).getByRole("button", { name: "Retry" }));
    await settle();
    expect(generation.calls).toEqual([["start", "t4"], ["start", "t4"]]);
    expect(steps().queryByRole("alert")).not.toBeInTheDocument();
    expect(steps().getByRole("status", { name: "Drafting steps" })).toBeInTheDocument();
  });
});
