import { render, renderHook, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test/server";
import StatusPage from "./status/page";
import {
  Providers,
  useClock,
  useDirectoryService,
  useStepGenerationService,
  useTaskService,
} from "./providers";
import { FakeTaskService } from "@/test/fakeServices";

// Matches NEXT_PUBLIC_API_URL in vitest.config.mts.
const API_URL = "http://localhost:8000";

describe("Providers", () => {
  it("wires the HTTP-backed HealthService to the configured API by default", async () => {
    server.use(
      http.get(`${API_URL}/health`, () => HttpResponse.json({ status: "ok" })),
      http.get(`${API_URL}/health/ready`, () =>
        HttpResponse.json({
          status: "ready",
          checks: [{ name: "database", status: "ok" }],
          ai: { provider: "fake", model: "fake-1" },
        }),
      ),
    );

    render(
      <Providers>
        <StatusPage />
      </Providers>,
    );

    expect(await screen.findByText(/all systems operational/i)).toBeInTheDocument();
    expect(screen.getByText("Database")).toBeInTheDocument();
  });

  it("shows the API as down, without crashing, when nothing is listening", async () => {
    server.use(http.get(`${API_URL}/health`, () => HttpResponse.error()));

    render(
      <Providers>
        <StatusPage />
      </Providers>,
    );

    expect(await screen.findByText(/api is unreachable/i)).toBeInTheDocument();
  });

  it("wires the in-memory task services only in explicit demo mode, sharing one store", async () => {
    const { result } = renderHook(
      () => ({ tasks: useTaskService(), directory: useDirectoryService(), generation: useStepGenerationService(), clock: useClock() }),
      { wrapper: ({ children }) => <Providers demo>{children}</Providers> },
    );

    expect(await result.current.tasks.list()).toHaveLength(16);
    expect((await result.current.directory.currentUser()).name).toBe("Andres Barradas");
    expect(Math.abs(result.current.clock() - Date.now())).toBeLessThan(1000);

    vi.useFakeTimers();
    try {
      await result.current.generation.start("t16");
      vi.advanceTimersByTime(2200);
      await result.current.generation.accept();
    } finally {
      vi.useRealTimers();
    }
    // Accepted through one service, visible through the other: they share a store.
    expect((await result.current.tasks.get("t16"))?.steps).toHaveLength(3);
  });

  it("selects real HTTP task services by default, never supplying seeded tasks", async () => {
    server.use(http.get(`${API_URL}/tasks`, ({ request }) => {
      expect(new URL(request.url).searchParams.get("status")).toBe("all");
      return HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 });
    }));
    const { result } = renderHook(() => useTaskService(), { wrapper: Providers });
    expect(await result.current.list()).toEqual([]);
  });

  it("keeps the same services across re-renders", () => {
    const { result, rerender } = renderHook(() => useTaskService(), { wrapper: Providers });
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it("lets a test replace a service and the clock", () => {
    const fake = new FakeTaskService();
    const { result } = renderHook(() => ({ tasks: useTaskService(), clock: useClock() }), {
      wrapper: ({ children }) => (
        <Providers taskService={fake} clock={() => 42}>
          {children}
        </Providers>
      ),
    });
    expect(result.current.tasks).toBe(fake);
    expect(result.current.clock()).toBe(42);
  });

  it.each([
    ["useTaskService", useTaskService],
    ["useDirectoryService", useDirectoryService],
    ["useStepGenerationService", useStepGenerationService],
    ["useClock", useClock],
  ])("%s refuses to run outside <Providers>", (_name, hook) => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => renderHook(() => hook())).toThrow(/Providers/);
    spy.mockRestore();
  });
});
