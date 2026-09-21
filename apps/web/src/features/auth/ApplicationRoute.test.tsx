import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import { ApiClient } from "@/lib/api/client";
import { server } from "@/test/server";
import { apiPerson } from "@/test/httpFixtures";
import { FakeDirectoryService, FakeStepGenerationService, FakeTaskService } from "@/test/fakeServices";
import { makeTask, NOW } from "@/test/tasks";
import type { TaskPage, TaskPageRequest } from "@/features/tasks/services/query";
import type { TaskService } from "@/features/tasks/services/types";
import { ApplicationRoute } from "./ApplicationRoute";
import { HttpAuthService } from "./service";

const { locationChanged } = vi.hoisted(() => ({ locationChanged: new EventTarget() }));
vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  const subscribe = (listener: () => void) => {
    locationChanged.addEventListener("change", listener);
    window.addEventListener("popstate", listener);
    return () => { locationChanged.removeEventListener("change", listener); window.removeEventListener("popstate", listener); };
  };
  const useHref = () => useSyncExternalStore(subscribe, () => `${location.pathname}${location.search}`);
  const router = {
    replace: (href: string) => history.replaceState(null, "", href),
    push: (href: string) => history.pushState(null, "", href),
  };
  return {
    usePathname: () => useHref().split("?")[0],
    useSearchParams: () => new URLSearchParams(useHref().split("?")[1] ?? ""),
    useRouter: () => router,
  };
});

const base = "http://localhost:8000";
const PROJECT_ID = "b334bf29-bf2e-400f-8e1a-9d5d47f10061";
const projects = [{ id: PROJECT_ID, name: "Marketing", tone: "accent" as const }];
const { pushState, replaceState } = history;
beforeEach(() => {
  // Next's native history integration re-renders its path/search hooks on these calls.
  history.pushState = (...args) => { pushState.apply(history, args); locationChanged.dispatchEvent(new Event("change")); };
  history.replaceState = (...args) => { replaceState.apply(history, args); locationChanged.dispatchEvent(new Event("change")); };
});
afterEach(() => {
  history.pushState = pushState;
  history.replaceState = replaceState;
  replaceState.call(history, null, "", "/");
});

function renderApp({ path = "/tasks", providerStatus = 200, taskService }: { path?: string; providerStatus?: number; taskService?: TaskService } = {}) {
  replaceState.call(history, null, "", path);
  server.use(http.get(`${base}/auth/sso/providers`, () => HttpResponse.json({ providers: [] }, { status: providerStatus })));
  const client: ApiClient = new ApiClient(base, { browser: true, token: () => auth.token(), version: () => auth.current().epoch, unauthorized: () => auth.expire() });
  const auth = new HttpAuthService(client, base, true);
  return render(
    <Providers authService={auth} taskService={taskService ?? new FakeTaskService([makeTask({ id: "t1", title: "Routed task", project: PROJECT_ID })])} directoryService={new FakeDirectoryService({ projects })} stepGenerationService={new FakeStepGenerationService()} clock={() => NOW}>
      <ApplicationRoute />
    </Providers>,
  );
}
function fill() {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "test@example.test" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password" } });
}
const signedIn = (user = apiPerson) => server.use(http.get(`${base}/auth/session`, () => HttpResponse.json(user)));
const unavailable = () => server.use(http.get(`${base}/auth/session`, () => new HttpResponse(null, { status: 503 })));
const backgroundCheck = () => act(() => { window.dispatchEvent(new Event("focus")); });
async function openDraft() {
  fireEvent.click(await screen.findByRole("button", { name: "Routed task" }));
  const description = await screen.findByRole("textbox", { name: "Description" });
  fireEvent.change(description, { target: { value: "Unsaved draft" } });
  return description;
}

describe("verified cookie auth screen", () => {
  it("signs in through HTTP, signs out, and verifies the persisted session on a full remount", async () => {
    let session = false;
    server.use(
      http.get(`${base}/auth/session`, () => session ? HttpResponse.json(apiPerson) : new HttpResponse(null, { status: 401 })),
      http.post(`${base}/auth/session`, () => { session = true; return HttpResponse.json(apiPerson); }),
      http.delete(`${base}/auth/session`, () => { session = false; return new HttpResponse(null, { status: 204 }); }),
    );
    const view = renderApp();
    expect(screen.queryByRole("button", { name: "Routed task" })).not.toBeInTheDocument();
    expect(await screen.findByText(/stay signed in across reloads/i)).toBeInTheDocument();
    expect(location.pathname).toBe("/login");
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("button", { name: "Routed task" });
    expect(location.pathname).toBe("/tasks");
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Routed task" })).not.toBeInTheDocument();
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("button", { name: "Routed task" });
    view.unmount();
    renderApp();
    expect(screen.queryByRole("heading", { name: "Welcome back" })).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Routed task" })).toBeInTheDocument();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("registers with a name and safely presents a duplicate email error with retry", async () => {
    server.use(http.get(`${base}/auth/session`, () => new HttpResponse(null, { status: 401 })), http.post(`${base}/auth/register`, () => HttpResponse.json({}, { status: 409 })));
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "Create an account" }));
    await waitFor(() => expect(location.pathname).toBe("/register"));
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Test Person" } });
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already registered/i);
    expect(screen.getByRole("button", { name: "Create account" })).toBeEnabled();
  });

  it("shows provider discovery errors without blocking password sign-in", async () => {
    server.use(http.get(`${base}/auth/session`, () => new HttpResponse(null, { status: 401 })));
    renderApp({ providerStatus: 503 });
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry single sign-on" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("withholds the workspace when the first session check is unavailable", async () => {
    unavailable();
    renderApp();
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not verify your session/i);
    expect(screen.queryByRole("button", { name: "Routed task" })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("Routed task");
  });
});

describe("background session checks", () => {
  it("hides an established workspace during a transient outage and restores its draft on a same-user retry", async () => {
    signedIn();
    renderApp();
    const description = await openDraft();
    unavailable();
    backgroundCheck();
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not verify your session/i);
    expect(description).toBeInTheDocument();
    expect(description).not.toBeVisible();
    expect(screen.queryByRole("textbox", { name: "Description" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Routed task" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
    signedIn();
    fireEvent.click(screen.getByRole("button", { name: "Retry session check" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Description" })).toBeVisible());
    expect(screen.getByRole("textbox", { name: "Description" })).toHaveValue("Unsaved draft");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("retires the preserved workspace when the retry verifies a different user", async () => {
    signedIn();
    renderApp();
    const description = await openDraft();
    unavailable();
    backgroundCheck();
    await screen.findByRole("alert");
    expect(description).toBeInTheDocument();
    expect(description).not.toBeVisible();
    expect(Array.from(document.querySelectorAll("textarea"), field => field.value)).toContain("Unsaved draft");
    signedIn({ ...apiPerson, id: "other-user", full_name: "Other Person" });
    fireEvent.click(screen.getByRole("button", { name: "Retry session check" }));
    await screen.findByRole("button", { name: "Routed task" });
    expect(screen.queryByRole("textbox", { name: "Description" })).not.toBeInTheDocument();
    expect(Array.from(document.querySelectorAll("textarea"), field => field.value)).not.toContain("Unsaved draft");
  });

  it("retires the preserved workspace when the retry finds the session expired", async () => {
    signedIn();
    renderApp();
    const description = await openDraft();
    unavailable();
    backgroundCheck();
    await screen.findByRole("alert");
    expect(description).toBeInTheDocument();
    expect(description).not.toBeVisible();
    expect(Array.from(document.querySelectorAll("textarea"), field => field.value)).toContain("Unsaved draft");
    server.use(http.get(`${base}/auth/session`, () => new HttpResponse(null, { status: 401 })));
    fireEvent.click(screen.getByRole("button", { name: "Retry session check" }));
    expect(await screen.findByText(/your session expired/i)).toBeInTheDocument();
    expect(location.pathname).toBe("/login");
    expect(Array.from(document.querySelectorAll("textarea"), field => field.value)).not.toContain("Unsaved draft");
  });
});

class PagedTasks extends FakeTaskService {
  total = 60;
  async query(request: TaskPageRequest): Promise<TaskPage> {
    return { tasks: [makeTask({ id: `row-${request.offset}`, title: `Row at ${request.offset}` })], total: this.total, headerTotal: this.total, limit: 50, offset: request.offset, sidebar: { all: this.total, mine: 0, overdue: 0, byProject: {} }, signals: { overdue: 0, critical: 0, soon: 0, unassigned: 0 } };
  }
}
async function traverse(step: "back" | "forward", expected: string) {
  act(() => { history[step](); });
  await waitFor(() => expect(`${location.pathname}${location.search}`).toBe(expected));
}

describe("automatic page correction", () => {
  it("replaces an out-of-range direct URL, so Back and Forward escape without a correction loop", async () => {
    signedIn();
    replaceState.call(history, null, "", "/tasks/mine");
    pushState.call(history, null, "", "/tasks?offset=100");
    const entries = history.length;
    renderApp({ path: "/tasks?offset=100", taskService: new PagedTasks() });
    expect(await screen.findByText("Row at 50")).toBeInTheDocument();
    expect(location.search).toBe("?offset=50");
    expect(history.length).toBe(entries);
    await traverse("back", "/tasks/mine");
    await screen.findByText("Row at 0");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(location.pathname).toBe("/tasks/mine");
    await traverse("forward", "/tasks?offset=50");
    expect(await screen.findByText("Row at 50")).toBeInTheDocument();
    expect(history.length).toBe(entries);
  });

  it("replaces a page that the results shrank beneath, keeping Back and Forward history", async () => {
    signedIn();
    const service = new PagedTasks();
    replaceState.call(history, null, "", "/tasks/mine");
    pushState.call(history, null, "", "/tasks?offset=50");
    const entries = history.length;
    renderApp({ path: "/tasks?offset=50", taskService: service });
    expect(await screen.findByText("Row at 50")).toBeInTheDocument();
    await traverse("back", "/tasks/mine");
    await screen.findByText("Row at 0");
    service.total = 40;
    await traverse("forward", "/tasks");
    expect(await screen.findByText("Row at 0")).toBeInTheDocument();
    expect(history.length).toBe(entries);
    await traverse("back", "/tasks/mine");
    await traverse("forward", "/tasks");
  });
});

describe("sidebar destinations", () => {
  it("links the selected project to itself while an ordinary click still toggles it off", async () => {
    signedIn();
    renderApp({ path: `/projects/${PROJECT_ID}?priority=1` });
    const projectNav = await screen.findByRole("navigation", { name: "Projects" });
    const link = await within(projectNav).findByRole("link", { name: /Marketing/ });
    expect(link).toHaveAttribute("href", `/projects/${PROJECT_ID}?priority=1`);
    expect(link).toHaveAttribute("aria-current", "page");
    expect(fireEvent.click(link, { ctrlKey: true })).toBe(true);
    expect(fireEvent.click(link, { button: 1 })).toBe(true);
    expect(location.pathname).toBe(`/projects/${PROJECT_ID}`);
    expect(fireEvent.click(link)).toBe(false);
    await waitFor(() => expect(`${location.pathname}${location.search}`).toBe("/tasks?priority=1"));
    const inactive = within(projectNav).getByRole("link", { name: /Marketing/ });
    expect(inactive).toHaveAttribute("href", `/projects/${PROJECT_ID}?priority=1`);
    expect(inactive).not.toHaveAttribute("aria-current");
  });
});
