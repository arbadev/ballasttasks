import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/server";
import Home from "./page";
import { Providers } from "./providers";

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
        <Home />
      </Providers>,
    );

    expect(await screen.findByText(/all systems operational/i)).toBeInTheDocument();
    expect(screen.getByText("Database")).toBeInTheDocument();
  });

  it("shows the API as down, without crashing, when nothing is listening", async () => {
    server.use(http.get(`${API_URL}/health`, () => HttpResponse.error()));

    render(
      <Providers>
        <Home />
      </Providers>,
    );

    expect(await screen.findByText(/api is unreachable/i)).toBeInTheDocument();
  });
});
