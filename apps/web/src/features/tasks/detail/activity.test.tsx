import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NOW, makeTask } from "@/test/tasks";
import { openTask, renderDetail, settle } from "./testing/renderDetail";

const HOUR = 36e5;
const section = () => within(screen.getByRole("region", { name: "Activity" }));
const entries = () => within(section().getByRole("list", { name: "Activity" })).getAllByRole("listitem");
const box = () => section().getByRole("textbox", { name: "Write a comment" });

/** A request the test holds open, so it can reject it after the user has typed again. */
function deferred() {
  let reject!: () => void;
  const promise = new Promise<never>((_resolve, rejectRequest) => {
    reject = () => rejectRequest(new Error("offline"));
  });
  return { promise, reject };
}

const TALKED_ABOUT = makeTask({
  id: "t1",
  activity: [
    { type: "comment", who: "lm", text: "I would accept due_before and due_after.", at: NOW - 27 * HOUR },
    { type: "log", who: "ab", text: "Created the task", at: NOW - 96 * HOUR },
    { type: "log", who: "ai", text: "Drafted 6 steps · added by Andres", at: NOW - 24 * HOUR },
    { type: "comment", who: "ab", text: "Agreed.", at: NOW - 12 * 60000 },
  ],
});

describe("activity", () => {
  it("is a timeline, oldest first, with who, a relative time and the text", async () => {
    await renderDetail({ tasks: [TALKED_ABOUT] });
    openTask("t1");
    expect(entries().map((li) => li.textContent)).toEqual([
      "ABAndres Barradas4 days agoCreated the task",
      "LMLucía Marínyesterday" + "I would accept due_before and due_after.",
      "AIAssistantyesterdayDrafted 6 steps · added by Andres",
      "ABAndres Barradas12 min agoAgreed.",
    ]);
  });

  it("sets comments apart from log lines", async () => {
    await renderDetail({ tasks: [TALKED_ABOUT] });
    openTask("t1");
    expect(entries().map((li) => li.getAttribute("data-kind"))).toEqual(["log", "comment", "log", "comment"]);
  });

  it("Enter posts the comment and clears the box", async () => {
    const { taskService } = await renderDetail({ tasks: [TALKED_ABOUT] });
    openTask("t1");
    expect(box()).toHaveAttribute("placeholder", "Write a comment — Enter to post");
    fireEvent.change(box(), { target: { value: "  Shipping it today. " } });
    const notCancelled = fireEvent.keyDown(box(), { key: "Enter" });
    await settle();

    expect(notCancelled).toBe(false);
    expect(taskService.calls).toContainEqual(["addComment", "t1", "Shipping it today."]);
    expect(box()).toHaveValue("");
    expect(entries()).toHaveLength(5);
    expect(entries()[4]).toHaveTextContent("Shipping it today.");
  });

  it("Shift+Enter is a new line, not a post", async () => {
    const { taskService } = await renderDetail({ tasks: [TALKED_ABOUT] });
    openTask("t1");
    fireEvent.change(box(), { target: { value: "first line" } });
    const notCancelled = fireEvent.keyDown(box(), { key: "Enter", shiftKey: true });
    await settle();
    expect(notCancelled).toBe(true);
    expect(taskService.calls.some((c) => c[0] === "addComment")).toBe(false);
    expect(box()).toHaveValue("first line");
  });

  it("an empty or blank comment does nothing, from Enter or from the button", async () => {
    const { taskService } = await renderDetail({ tasks: [TALKED_ABOUT] });
    openTask("t1");
    fireEvent.keyDown(box(), { key: "Enter" });
    fireEvent.change(box(), { target: { value: "   " } });
    fireEvent.click(section().getByRole("button", { name: "Comment" }));
    await settle();
    expect(taskService.calls.some((c) => c[0] === "addComment")).toBe(false);
    expect(entries()).toHaveLength(4);
  });

  it("the Comment button posts too", async () => {
    const { taskService } = await renderDetail({ tasks: [TALKED_ABOUT] });
    openTask("t1");
    fireEvent.change(box(), { target: { value: "From the button" } });
    fireEvent.click(section().getByRole("button", { name: "Comment" }));
    await settle();
    expect(taskService.calls).toContainEqual(["addComment", "t1", "From the button"]);
  });

  it("keeps a half-written comment when the panel closes and reopens", async () => {
    await renderDetail({ tasks: [TALKED_ABOUT] });
    openTask("t1");
    fireEvent.change(box(), { target: { value: "not posted yet" } });
    fireEvent.keyDown(window, { key: "Escape" });
    openTask("t1");
    expect(box()).toHaveValue("not posted yet");
  });

  it("puts a comment back in the box when posting fails, and says so", async () => {
    const { taskService } = await renderDetail({ tasks: [TALKED_ABOUT] });
    taskService.addComment = async () => {
      throw new Error("offline");
    };
    openTask("t1");
    fireEvent.change(box(), { target: { value: "Will bounce" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    await settle();
    expect(box()).toHaveValue("Will bounce");
    expect(section().getByRole("alert")).toHaveTextContent("Could not post the comment.");
  });

  it("keeps what was typed since, and Retry sends the comment that failed", async () => {
    const { taskService } = await renderDetail({ tasks: [TALKED_ABOUT] });
    const original = taskService.addComment.bind(taskService);
    const held = deferred();
    taskService.addComment = () => held.promise;
    openTask("t1");

    fireEvent.change(box(), { target: { value: "Will bounce" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    await settle();
    fireEvent.change(box(), { target: { value: "Typed while it was in flight" } });

    held.reject();
    await settle();
    expect(box()).toHaveValue("Typed while it was in flight");
    expect(section().getByRole("alert")).toHaveTextContent("Could not post the comment.");

    taskService.addComment = original;
    fireEvent.click(within(section().getByRole("alert")).getByRole("button", { name: "Retry" }));
    await settle();
    expect(taskService.calls).toContainEqual(["addComment", "t1", "Will bounce"]);
    expect(box()).toHaveValue("Typed while it was in flight");
    expect(section().queryByRole("alert")).not.toBeInTheDocument();
  });
});
