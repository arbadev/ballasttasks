import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import { InMemoryTaskService } from "../services/inMemoryTaskService";
import { InMemoryTaskStore } from "../services/inMemoryTaskStore";
import { WorkspaceProvider, useWorkspace } from "../workspace/WorkspaceProvider";
import { FakeDirectoryService, FakeStepGenerationService } from "@/test/fakeServices";
import { NOW } from "@/test/tasks";
import { TaskDetail } from "./TaskDetail";
import { settle } from "./testing/renderDetail";

function Openers() {
  const { actions } = useWorkspace();
  return <button onClick={() => actions.selectTask("t4")}>Open task</button>;
}

async function setup() {
  const store = new InMemoryTaskStore(() => NOW);
  const service = new InMemoryTaskService(store);
  render(<Providers taskService={service} directoryService={new FakeDirectoryService()} stepGenerationService={new FakeStepGenerationService()} clock={() => NOW}>
    <WorkspaceProvider><Openers /><TaskDetail /></WorkspaceProvider>
  </Providers>);
  await settle();
  fireEvent.click(screen.getByRole("button", { name: "Open task" }));
  const section = within(screen.getByRole("region", { name: "Attachments" }));
  return { store, service, section };
}

const file = (type = "application/pdf", name = "exercise.pdf", size = 2048) => new File([new Uint8Array(size)], name, { type });

describe("real attachment flow over the in-memory service", () => {
  it.each([
    ["application/pdf", "exercise.pdf", "pdf", "PDF"],
    ["image/png", "reference.png", "image", "PNG"],
    ["image/jpeg", "photo.jpg", "image", "JPG"],
    ["image/gif", "animation.gif", "image", "GIF"],
    ["image/webp", "board.webp", "image", "WEBP"],
  ])("uploads %s through the service with its real file and final metadata", async (type, name, kind, label) => {
    const { store, service, section } = await setup();
    const add = vi.spyOn(service, "addAttachment");
    const selected = file(type, name);
    fireEvent.change(section.getByLabelText("Choose a file to attach"), { target: { files: [selected] } });
    await settle();
    expect(add).toHaveBeenCalledWith("t4", { kind, name, meta: `${label} · 2 KB` }, selected);
    expect(store.require("t4").attachments).toEqual([{ kind, name, meta: `${label} · 2 KB` }]);
    expect(store.require("t4").activity.at(-1)?.text).toBe(`Attached ${name}`);
    expect(section.getByText(`${label} · 2 KB`)).toBeVisible();
    expect(section.queryByText(/uploading/)).not.toBeInTheDocument();
  });

  it("opens the native file picker from an enabled keyboard-operable button", async () => {
    const { section } = await setup();
    const input = section.getByLabelText("Choose a file to attach");
    const click = vi.spyOn(input, "click");
    const button = section.getByRole("button", { name: "Attach file" });
    button.focus();
    expect(button).toHaveFocus();
    expect(button).not.toHaveAttribute("aria-disabled", "true");
    fireEvent.click(button);
    expect(click).toHaveBeenCalledOnce();
    expect(input).toHaveAttribute("type", "file");
  });

  it("shows uploading metadata only while the service is pending, then the saved metadata", async () => {
    const { service, section } = await setup();
    const original = service.addAttachment.bind(service);
    let release!: () => void;
    vi.spyOn(service, "addAttachment").mockImplementation(async (...args) => {
      await new Promise<void>((resolve) => { release = resolve; });
      return original(...args);
    });
    fireEvent.change(section.getByLabelText("Choose a file to attach"), { target: { files: [file()] } });
    expect(section.getByText("PDF · uploading…")).toBeVisible();
    expect(section.getByRole("button", { name: "Attach file" })).toBeDisabled();
    await act(async () => release());
    expect(section.queryByText(/uploading/)).not.toBeInTheDocument();
    expect(section.getByText("PDF · 2 KB")).toBeVisible();
  });

  it.each([
    ["text/html", "page.html", 16, /Choose a PDF or a PNG, JPG, GIF or WEBP image/],
    ["image/svg+xml", "unsafe.svg", 16, /Choose a PDF or a PNG, JPG, GIF or WEBP image/],
    ["application/pdf", "large.pdf", 10 * 1024 * 1024 + 1, /10 MB or smaller/],
  ])("rejects invalid %s files without adding an attachment", async (type, name, size, message) => {
    const { store, service, section } = await setup();
    const add = vi.spyOn(service, "addAttachment");
    fireEvent.change(section.getByLabelText("Choose a file to attach"), { target: { files: [file(type, name, size)] } });
    await settle();
    expect(section.getByRole("alert")).toHaveTextContent(message);
    expect(add).not.toHaveBeenCalled();
    expect(store.require("t4").attachments).toEqual([]);
  });

  it("accepts the 10 MB boundary and a dropped file", async () => {
    const { store } = await setup();
    fireEvent.drop(screen.getByRole("region", { name: "Attachments" }), { dataTransfer: { files: [file("application/pdf", "boundary.pdf", 10 * 1024 * 1024)] } });
    await settle();
    expect(store.require("t4").attachments).toEqual([{ kind: "pdf", name: "boundary.pdf", meta: "PDF · 10 MB" }]);
  });

  it("removes a failed uploading tile, reports the error, and allows reselecting the file", async () => {
    const { store, service, section } = await setup();
    vi.spyOn(service, "addAttachment").mockRejectedValueOnce(new Error("offline"));
    const input = section.getByLabelText("Choose a file to attach");
    const selected = file();
    fireEvent.change(input, { target: { files: [selected] } });
    await settle();
    expect(section.getByRole("alert")).toHaveTextContent("Could not attach the file. Try again.");
    expect(store.require("t4").attachments).toEqual([]);
    expect(section.queryByText(/uploading/)).not.toBeInTheDocument();
    fireEvent.change(input, { target: { files: [selected] } });
    await settle();
    expect(section.queryByRole("alert")).not.toBeInTheDocument();
    expect(store.require("t4").attachments).toHaveLength(1);
  });

  it("stores nothing for an address that is not a web link, then keeps the one that is", async () => {
    const { store, section } = await setup();
    fireEvent.click(section.getByRole("button", { name: "Add link" }));
    const field = section.getByRole("textbox", { name: "Link URL" });
    const form = section.getByRole("form", { name: "Add a link" });

    for (const bad of ["mailto:someone@example.com", "javascript:alert(1)", "data:text/html,<b>x", "file:///etc/passwd", "tel:+1234", "ftp://example.com", "https://u:p@example.com"]) {
      fireEvent.change(field, { target: { value: bad } });
      fireEvent.submit(form);
      await settle();
      expect(section.getByRole("alert"), bad).toHaveTextContent("Enter a web address, like https://example.com");
      expect(store.require("t4").attachments, bad).toEqual([]);
      expect(section.queryAllByRole("link"), bad).toHaveLength(0);
    }

    fireEvent.change(field, { target: { value: "example.com/a?b=1#c" } });
    fireEvent.submit(form);
    await settle();
    const link = section.getByRole("link", { name: /example\.com\/a/ });
    expect(link).toHaveAttribute("href", "https://example.com/a?b=1#c");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(store.require("t4").attachments).toEqual([{ kind: "link", name: "example.com/a", meta: "example.com", url: "https://example.com/a?b=1#c" }]);
  });

  it("keeps full link URLs including query and hash, and opens distinct links safely", async () => {
    const { store, section } = await setup();
    for (const query of ["first", "second"]) {
      fireEvent.click(section.getByRole("button", { name: "Add link" }));
      fireEvent.change(section.getByRole("textbox", { name: "Link URL" }), { target: { value: `https://example.com/docs?q=${query}#section` } });
      fireEvent.submit(section.getByRole("form", { name: "Add a link" }));
      await settle();
    }
    const links = section.getAllByRole("link", { name: /example.com\/docs/ });
    expect(links).toHaveLength(2);
    for (const [i, query] of ["first", "second"].entries()) {
      expect(links[i]).toHaveAttribute("href", `https://example.com/docs?q=${query}#section`);
      expect(links[i]).toHaveAttribute("target", "_blank");
      expect(links[i]).toHaveAttribute("rel", "noopener noreferrer");
    }
    expect(store.require("t4").attachments).toEqual(["first", "second"].map((query) => ({ kind: "link", name: "example.com/docs", meta: "example.com", url: `https://example.com/docs?q=${query}#section` })));
  });
});
