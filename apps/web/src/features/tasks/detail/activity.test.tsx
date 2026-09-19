import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NOW, makeTask } from "@/test/tasks";
import type { FakeTaskService } from "@/test/fakeServices";
import { openTask, renderDetail, settle } from "./testing/renderDetail";

const HOUR = 36e5;
const section = () => within(screen.getByRole("region", { name: "Activity" }));
const entries = () => within(section().getByRole("list", { name: "Activity" })).getAllByRole("listitem");
const box = () => section().getByRole("textbox", { name: "Write a comment" });

/** Rejects every post, recording the attempt, so a test can count what was actually sent. */
const rejectAddComment = (service: FakeTaskService) => async (id: string, text: string) => {
  service.calls.push(["addComment:rejected", id, text]);
  throw new Error("offline");
};

/** A request the test holds open, so it can refuse it at the moment the trace calls for. */
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

  it("clears the box on a Retry that lands, so the comment is not posted twice", async () => {
    const { taskService } = await renderDetail({ tasks: [TALKED_ABOUT] });
    const original = taskService.addComment.bind(taskService);
    taskService.addComment = rejectAddComment(taskService);
    openTask("t1");

    fireEvent.change(box(), { target: { value: "Will bounce" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    await settle();
    expect(box()).toHaveValue("Will bounce");

    taskService.addComment = original;
    fireEvent.click(within(section().getByRole("alert")).getByRole("button", { name: "Retry" }));
    await settle();
    expect(box()).toHaveValue("");

    fireEvent.keyDown(box(), { key: "Enter" });
    await settle();
    expect(taskService.calls.filter((c) => c[0] === "addComment")).toHaveLength(1);
  });

  it("keeps the comment that failed until it is retried or dismissed", async () => {
    const { taskService } = await renderDetail({ tasks: [TALKED_ABOUT] });
    taskService.addComment = rejectAddComment(taskService);
    openTask("t1");

    fireEvent.change(box(), { target: { value: "Ping the vendor" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    await settle();
    expect(section().getByRole("alert")).toHaveTextContent("Could not post the comment.");

    fireEvent.change(box(), { target: { value: "Following up separately" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    await settle();
    expect(taskService.calls.filter((c) => c[0] === "addComment:rejected")).toHaveLength(1);
    expect(section().getByRole("alert")).toHaveTextContent("Could not post the comment.");
    expect(box()).toHaveValue("Following up separately");

    fireEvent.click(within(section().getByRole("alert")).getByRole("button", { name: "Dismiss" }));
    expect(section().queryByRole("alert")).not.toBeInTheDocument();
    expect(box()).toHaveValue("Following up separately");
  });

  it("sees a post that answered while the panel was shut, and a Retry after that clears only its own text", async () => {
    const { taskService } = await renderDetail({ tasks: [TALKED_ABOUT] });
    const original = taskService.addComment.bind(taskService);
    const held = deferred();
    taskService.addComment = () => held.promise;
    openTask("t1");

    fireEvent.change(box(), { target: { value: "Ping the vendor" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    await settle();
    expect(section().getByRole("status")).toHaveTextContent("Posting comment…");

    fireEvent.keyDown(window, { key: "Escape" });
    held.reject();
    await settle();

    openTask("t1");
    expect(section().getByRole("alert")).toHaveTextContent("Could not post the comment.");
    expect(box()).toHaveValue("Ping the vendor");

    taskService.addComment = original;
    fireEvent.click(within(section().getByRole("alert")).getByRole("button", { name: "Retry" }));
    await settle();
    expect(taskService.calls).toContainEqual(["addComment", "t1", "Ping the vendor"]);
    expect(box()).toHaveValue("");

    fireEvent.keyDown(box(), { key: "Enter" });
    await settle();
    expect(taskService.calls.filter((c) => c[0] === "addComment")).toHaveLength(1);
  });

  it("says it is posting, takes one post at a time, and keeps the next draft", async () => {
    const { taskService } = await renderDetail({ tasks: [TALKED_ABOUT] });
    const original = taskService.addComment.bind(taskService);
    let release!: () => void;
    taskService.addComment = (id, text) => new Promise<void>((resolve) => (release = resolve)).then(() => original(id, text));
    openTask("t1");

    fireEvent.change(box(), { target: { value: "First comment" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    await settle();
    expect(section().getByRole("status")).toHaveTextContent("Posting comment…");
    expect(section().getByRole("button", { name: "Comment" })).toBeDisabled();

    fireEvent.change(box(), { target: { value: "Second comment" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    fireEvent.click(section().getByRole("button", { name: "Comment" }));
    await settle();
    expect(taskService.calls.filter((c) => c[0] === "addComment")).toHaveLength(0);
    expect(box()).toHaveValue("Second comment");

    release();
    await settle();
    expect(taskService.calls).toContainEqual(["addComment", "t1", "First comment"]);
    expect(section().queryByRole("status")).not.toBeInTheDocument();
    expect(section().getByRole("button", { name: "Comment" })).toBeEnabled();
    expect(box()).toHaveValue("Second comment");
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
