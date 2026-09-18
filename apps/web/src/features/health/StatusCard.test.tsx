import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import { StatusCard } from "./StatusCard";
import type { HealthService, HealthViewModel } from "./service";

const healthy: HealthViewModel = {
  apiReachable: true,
  ready: true,
  components: [
    { name: "database", label: "Database", ok: true },
    { name: "redis", label: "Redis", ok: true },
    { name: "ai", label: "AI", ok: true },
  ],
  ai: { provider: "fake", model: "fake-1" },
};

// A fake HealthService: these tests never touch the HTTP client or the network.
const fakeService = (getHealth: HealthService["getHealth"]): HealthService => ({ getHealth });

const renderCard = (service: HealthService) =>
  render(
    <Providers healthService={service}>
      <StatusCard />
    </Providers>,
  );

const row = (label: string) => screen.getByRole("listitem", { name: new RegExp(`^${label}`) });

describe("StatusCard", () => {
  it("shows a loading state until the service answers", async () => {
    let resolve!: (value: HealthViewModel) => void;
    const pending = new Promise<HealthViewModel>((r) => (resolve = r));

    renderCard(fakeService(() => pending));

    expect(screen.getByText(/checking system status/i)).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();

    resolve(healthy);
    expect(await screen.findByRole("list")).toBeInTheDocument();
    expect(screen.queryByText(/checking system status/i)).not.toBeInTheDocument();
  });

  it("shows every component as OK when all checks pass", async () => {
    renderCard(fakeService(async () => healthy));

    expect(await screen.findByText(/all systems operational/i)).toBeInTheDocument();
    for (const label of ["API", "Database", "Redis", "AI"]) {
      expect(within(row(label)).getByText("OK")).toBeInTheDocument();
    }
    expect(screen.queryByText("Failing")).not.toBeInTheDocument();
  });

  it("marks only the failing component when one check fails", async () => {
    renderCard(
      fakeService(async () => ({
        ...healthy,
        ready: false,
        components: healthy.components.map((c) => (c.name === "redis" ? { ...c, ok: false } : c)),
      })),
    );

    expect(await screen.findByText(/some systems are failing/i)).toBeInTheDocument();
    expect(within(row("Redis")).getByText("Failing")).toBeInTheDocument();
    expect(within(row("Database")).getByText("OK")).toBeInTheDocument();
    expect(within(row("API")).getByText("OK")).toBeInTheDocument();
  });

  it("renders the AI provider and model", async () => {
    renderCard(fakeService(async () => healthy));

    expect(await screen.findByText("fake")).toBeInTheDocument();
    expect(screen.getByText("fake-1")).toBeInTheDocument();
  });

  it("shows the API as failing when it is unreachable", async () => {
    renderCard(
      fakeService(async () => ({ apiReachable: false, ready: false, components: [], ai: null })),
    );

    expect(await screen.findByText(/api is unreachable/i)).toBeInTheDocument();
    expect(within(row("API")).getByText("Failing")).toBeInTheDocument();
  });

  it("shows an error message when the service fails", async () => {
    renderCard(
      fakeService(async () => {
        throw new Error("boom");
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not load system status/i);
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("reloads the status when refresh is pressed", async () => {
    const getHealth = vi
      .fn<HealthService["getHealth"]>()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(healthy);

    renderCard(fakeService(getHealth));
    await screen.findByRole("alert");

    screen.getByRole("button", { name: /refresh/i }).click();

    expect(await screen.findByText(/all systems operational/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(getHealth).toHaveBeenCalledTimes(2);
  });

  it("refuses to render outside the provider", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => render(<StatusCard />)).toThrow(/Providers/);

    consoleError.mockRestore();
  });
});
