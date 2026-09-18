import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { ApiClient, ApiError } from "@/lib/api/client";
import { server } from "@/test/server";
import { HttpHealthService } from "./service";

const BASE_URL = "http://api.test";

const service = () => new HttpHealthService(new ApiClient(BASE_URL));

const liveness = (status = 200) =>
  http.get(`${BASE_URL}/health`, () => HttpResponse.json({ status: "ok" }, { status }));

describe("HttpHealthService", () => {
  it("maps a ready API response to the view model", async () => {
    server.use(
      liveness(),
      http.get(`${BASE_URL}/health/ready`, () =>
        HttpResponse.json({
          status: "ready",
          checks: [
            { name: "database", status: "ok" },
            { name: "redis", status: "ok" },
            { name: "ai", status: "ok" },
          ],
          ai: { provider: "fake", model: "fake-1" },
        }),
      ),
    );

    await expect(service().getHealth()).resolves.toEqual({
      apiReachable: true,
      ready: true,
      components: [
        { name: "database", label: "Database", ok: true },
        { name: "redis", label: "Redis", ok: true },
        { name: "ai", label: "AI", ok: true },
      ],
      ai: { provider: "fake", model: "fake-1" },
    });
  });

  it("still parses a 503 body into per-component statuses", async () => {
    server.use(
      liveness(),
      http.get(`${BASE_URL}/health/ready`, () =>
        HttpResponse.json(
          {
            status: "not_ready",
            checks: [
              { name: "database", status: "ok" },
              { name: "redis", status: "failed" },
              { name: "ai", status: "ok" },
            ],
            ai: { provider: "fake", model: "fake-1" },
          },
          { status: 503 },
        ),
      ),
    );

    const health = await service().getHealth();

    expect(health.apiReachable).toBe(true);
    expect(health.ready).toBe(false);
    expect(health.components).toEqual([
      { name: "database", label: "Database", ok: true },
      { name: "redis", label: "Redis", ok: false },
      { name: "ai", label: "AI", ok: true },
    ]);
    expect(health.ai).toEqual({ provider: "fake", model: "fake-1" });
  });

  it("renders an unknown check name with the raw name as its label", async () => {
    server.use(
      liveness(),
      http.get(`${BASE_URL}/health/ready`, () =>
        HttpResponse.json({
          status: "ready",
          checks: [{ name: "object_storage", status: "ok" }],
          ai: { provider: "fake", model: "fake-1" },
        }),
      ),
    );

    const health = await service().getHealth();

    expect(health.components).toEqual([{ name: "object_storage", label: "object_storage", ok: true }]);
  });

  it("reports the API as unreachable on a network failure instead of rejecting", async () => {
    server.use(http.get(`${BASE_URL}/health`, () => HttpResponse.error()));

    await expect(service().getHealth()).resolves.toEqual({
      apiReachable: false,
      ready: false,
      components: [],
      ai: null,
    });
  });

  it("rejects when a 503 body is not a readiness response", async () => {
    server.use(
      liveness(),
      http.get(`${BASE_URL}/health/ready`, () =>
        HttpResponse.json({ detail: "upstream" }, { status: 503 }),
      ),
    );

    await expect(service().getHealth()).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects on an unexpected error status from readiness", async () => {
    server.use(
      liveness(),
      http.get(`${BASE_URL}/health/ready`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    await expect(service().getHealth()).rejects.toBeInstanceOf(ApiError);
  });

  it("rejects when liveness answers with an error status", async () => {
    server.use(liveness(500));

    await expect(service().getHealth()).rejects.toBeInstanceOf(ApiError);
  });
});
