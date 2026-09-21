import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FakeQueryTaskService } from "@/test/fakeServices";
import { renderWithServices } from "@/test/renderWithServices";
import { makeTask } from "@/test/tasks";
import type { TaskPatch } from "../services/types";
import { TasksApp } from "../shell/TasksApp";
import { AUTOSAVE_DELAY_MS } from "./useAutosaveField";

/** The API trims titles; the ordinary fake deliberately does not. Keep that boundary here. */
class CanonicalTitles extends FakeQueryTaskService {
  readonly submitted: TaskPatch[] = [];
  override async update(id: string, patch: TaskPatch, note?: string) {
    this.submitted.push(patch);
    return super.update(id, patch.title === undefined ? patch : { ...patch, title: patch.title.trim() }, note);
  }
}

async function setup() {
  const task = makeTask({ id: "typing", title: "Original title", detailLoaded: true });
  const service = new CanonicalTitles([task]);
  renderWithServices(<TasksApp />, { taskService: service });
  fireEvent.click(await screen.findByRole("button", { name: task.title }));
  const input = screen.getByRole("textbox", { name: "Task name" }) as HTMLInputElement;
  act(() => input.focus());
  return { service, input };
}

// DOM event simulation, not native keyboard proof (the HTTP browser contract supplies that).
function replace(input: HTMLInputElement, value: string, position = value.length) {
  fireEvent.change(input, { target: { value } });
  input.setSelectionRange(position, position);
}
function type(input: HTMLInputElement, text: string) {
  for (const char of text) {
    const start = input.selectionStart!, end = input.selectionEnd!;
    replace(input, input.value.slice(0, start) + char + input.value.slice(end), start + char.length);
  }
}
const pause = () => act(async () => { await new Promise(resolve => setTimeout(resolve, AUTOSAVE_DELAY_MS + 80)); });
const saved = () => expect(screen.getByTestId("save-state")).toHaveTextContent(/^saved · /);

function caret(input: HTMLInputElement, value: string, position = value.length) {
  expect(screen.getByRole("textbox", { name: "Task name" })).toBe(input);
  expect(input).toHaveFocus();
  expect(input).toHaveValue(value);
  expect([input.selectionStart, input.selectionEnd]).toEqual([position, position]);
}

describe("title typing through the shell and canonical query refresh", () => {
  it("keeps a word separator and caret after autosave, then flushes canonical text on blur/close", async () => {
    const { service, input } = await setup();
    replace(input, "");
    type(input, "Write a ");
    expect(service.submitted).toEqual([]);
    await pause();
    saved();
    expect((await service.get("typing"))?.title).toBe("Write a");
    caret(input, "Write a ");
    type(input, "multiword title");
    await pause();
    saved();
    caret(input, "Write a multiword title");
    expect(service.submitted).toEqual([{ title: "Write a " }, { title: "Write a multiword title" }]);

    type(input, " ");
    await pause();
    caret(input, "Write a multiword title ");
    act(() => screen.getByRole("textbox", { name: "Description" }).focus());
    expect(input).toHaveValue("Write a multiword title");
    expect(service.submitted).toHaveLength(3); // blur of an acknowledged draft does not write again

    act(() => input.focus());
    input.setSelectionRange(input.value.length, input.value.length);
    type(input, " before close");
    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    fireEvent.click(await screen.findByRole("button", { name: "Write a multiword title before close" }));
    expect(screen.getByRole("textbox", { name: "Task name" })).toHaveValue("Write a multiword title before close");
    expect(service.submitted).toHaveLength(4);
  });

  it("keeps replacement and middle insertion while a save is in flight", async () => {
    const { service, input } = await setup();
    const held = service.holdNext("update");
    replace(input, "");
    type(input, "First ");
    await pause();
    expect(screen.getByTestId("save-state")).toHaveTextContent("saving…");
    type(input, "draft words");
    input.setSelectionRange(5, 5);
    type(input, " middle");
    const intended = "First middle draft words";
    caret(input, intended, 12);
    await act(async () => held.release());
    caret(input, intended, 12);
    await pause();
    saved();
    caret(input, intended, 12);
    expect(service.submitted).toEqual([{ title: "First " }, { title: intended }]);
    expect((await service.get("typing"))?.title).toBe(intended);
  });

  it("keeps a newer draft on genuine refusal and retries the exact rejected title", async () => {
    const { service, input } = await setup();
    const held = service.holdNext("update");
    replace(input, "");
    type(input, "Refused ");
    await pause();
    type(input, "new draft");
    await act(async () => held.fail(new Error("refused")));
    caret(input, "Refused new draft");
    expect(screen.getByRole("alert")).toHaveTextContent("Could not save the title.");
    expect(screen.getByTestId("save-state")).toHaveTextContent("not saved");
    await pause();
    saved();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    const rejected = service.holdNext("update");
    type(input, "!");
    await pause();
    await act(async () => rejected.fail(new Error("refused again")));
    expect(input).toHaveValue("Refused new draft");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(saved);
    expect(input).toHaveValue("Refused new draft!");
    expect(service.submitted).toEqual([
      { title: "Refused " }, { title: "Refused new draft" }, { title: "Refused new draft!" }, { title: "Refused new draft!" },
    ]);
  });
});
