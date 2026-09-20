import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeTask } from "@/test/tasks";
import { openTask, renderDetail, settle } from "./testing/renderDetail";

const section = () => within(screen.getByRole("region", { name: "Attachments" }));
const items = () => within(section().getByRole("list", { name: "Attachments" })).getAllByRole("listitem");

const THREE_KINDS = makeTask({
  id: "t1",
  attachments: [
    { kind: "pdf", name: "Exercise.pdf", meta: "PDF · 3 pages · 84 KB" },
    { kind: "image", name: "board-reference.png", meta: "PNG · 1514×856" },
    { kind: "link", name: "Swagger UI", meta: "localhost:8000/docs", url: "http://localhost:8000/docs" },
  ],
});

describe("attachments", () => {
  it("lists the three kinds with their name, secondary line and kind", async () => {
    await renderDetail({ tasks: [THREE_KINDS] });
    openTask("t1");
    expect(section().getByTestId("attachment-count")).toHaveTextContent("3");
    expect(items().map((li) => li.textContent)).toEqual(["Exercise.pdfPDF · 3 pages · 84 KB", "board-reference.pngPNG · 1514×856", "Swagger UIlocalhost:8000/docs"]);
    expect(items().map((li) => within(li).getByRole("img").getAttribute("aria-label"))).toEqual(["PDF", "Image", "Link"]);
  });

  it("explains that files and links are references, not inputs to drafting steps", async () => {
    await renderDetail({ tasks: [makeTask({ id: "t1" })] });
    openTask("t1");
    expect(section().getByTestId("attachment-count")).toHaveTextContent("0");
    expect(section().queryByRole("list", { name: "Attachments" })).not.toBeInTheDocument();
    expect(section().getByTestId("attachments-empty")).toHaveTextContent("Drop files here, or paste a link — reference files and links aren't read when drafting steps.");
    expect(section().getByRole("button", { name: "Attach file" })).toBeEnabled();
    expect(section().getByRole("button", { name: "Add link" })).toBeEnabled();
  });

  it("cancelling the file picker adds nothing", async () => {
    const { taskService } = await renderDetail({ tasks: [makeTask({ id: "t1" })] });
    openTask("t1");
    const attach = section().getByRole("button", { name: "Attach file" });
    expect(attach).toBeEnabled();
    fireEvent.click(attach);
    fireEvent.change(section().getByLabelText("Choose a file to attach"), { target: { files: [] } });
    await settle();
    expect(taskService.calls.some((c) => c[0] === "addAttachment")).toBe(false);
  });

  it("Add link opens a labelled form with the URL focused", async () => {
    await renderDetail({ tasks: [makeTask({ id: "t1" })] });
    openTask("t1");
    const toggle = section().getByRole("button", { name: "Add link" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // Collapsed there is no form to point at, and a dangling IDREF is an invalid value.
    expect(toggle).not.toHaveAttribute("aria-controls");

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAttribute("aria-controls", section().getByRole("form", { name: "Add a link" }).id);
    expect(section().getByRole("textbox", { name: "Link URL" })).toHaveFocus();
    expect(section().getByRole("textbox", { name: "Title (optional)" })).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(section().queryByRole("form", { name: "Add a link" })).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).not.toHaveAttribute("aria-controls");
  });

  it("rejects an invalid address inline, without calling the service", async () => {
    const { taskService } = await renderDetail({ tasks: [makeTask({ id: "t1" })] });
    openTask("t1");
    fireEvent.click(section().getByRole("button", { name: "Add link" }));
    const url = section().getByRole("textbox", { name: "Link URL" });
    fireEvent.change(url, { target: { value: "not a link" } });
    fireEvent.click(section().getByRole("button", { name: "Add" }));
    await settle();

    expect(section().getByRole("alert")).toHaveTextContent("Enter a web address, like https://example.com");
    expect(url).toHaveAttribute("aria-invalid", "true");
    expect(taskService.calls.some((c) => c[0] === "addAttachment")).toBe(false);

    fireEvent.change(url, { target: { value: "https://example.com" } });
    expect(section().queryByRole("alert")).not.toBeInTheDocument();
  });

  it("adds a titled link through the service, closes the form and lists it", async () => {
    const { taskService } = await renderDetail({ tasks: [makeTask({ id: "t1" })] });
    openTask("t1");
    fireEvent.click(section().getByRole("button", { name: "Add link" }));
    fireEvent.change(section().getByRole("textbox", { name: "Link URL" }), { target: { value: "https://github.com/arbadev/ballasttasks" } });
    fireEvent.change(section().getByRole("textbox", { name: "Title (optional)" }), { target: { value: "Repository" } });
    fireEvent.submit(section().getByRole("form", { name: "Add a link" }));
    await settle();

    expect(taskService.calls).toContainEqual(["addAttachment", "t1", { kind: "link", name: "Repository", meta: "github.com", url: "https://github.com/arbadev/ballasttasks" }]);
    expect(section().queryByRole("form", { name: "Add a link" })).not.toBeInTheDocument();
    expect(items().map((li) => li.textContent)).toEqual(["Repositorygithub.com"]);
    expect(section().getByRole("button", { name: "Add link" })).toHaveFocus();
  });

  it("names an untitled link after its address", async () => {
    const { taskService } = await renderDetail({ tasks: [makeTask({ id: "t1" })] });
    openTask("t1");
    fireEvent.click(section().getByRole("button", { name: "Add link" }));
    fireEvent.change(section().getByRole("textbox", { name: "Link URL" }), { target: { value: "vectal.ai/toolkit" } });
    fireEvent.submit(section().getByRole("form", { name: "Add a link" }));
    await settle();
    expect(taskService.calls).toContainEqual(["addAttachment", "t1", { kind: "link", name: "vectal.ai/toolkit", meta: "vectal.ai", url: "https://vectal.ai/toolkit" }]);
  });

  it("Escape and Cancel close the form without closing the panel", async () => {
    await renderDetail({ tasks: [makeTask({ id: "t1" })] });
    openTask("t1");
    fireEvent.click(section().getByRole("button", { name: "Add link" }));
    const url = section().getByRole("textbox", { name: "Link URL" });
    const notCancelled = fireEvent.keyDown(url, { key: "Escape" });
    expect(notCancelled).toBe(false);
    expect(section().queryByRole("form", { name: "Add a link" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(section().getByRole("button", { name: "Add link" }));
    fireEvent.click(section().getByRole("button", { name: "Cancel" }));
    expect(section().queryByRole("form", { name: "Add a link" })).not.toBeInTheDocument();
  });
});
