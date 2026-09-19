// @vitest-environment node
// Use one native Fetch/FormData/File realm for executable HTTP transport contracts.
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test/server";
import { ApiClient, ApiError } from "./client";

const BASE_URL = "http://api.test";

async function captureError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    return error as ApiError;
  }
  throw new Error("expected the request to reject");
}

describe("ApiClient", () => {
  it("sends JSON mutations with the current bearer credential only in headers", async () => {
    server.use(http.patch(`${BASE_URL}/tasks/task-id`, async ({ request }) => {
      expect(request.headers.get("Authorization")).toBe("Bearer private-token");
      expect(request.url).not.toContain("private-token");
      expect(request.headers.get("Content-Type")).toBe("application/json");
      expect(await request.json()).toEqual({ due_date: null });
      return HttpResponse.json({ id: "task-id" });
    }));
    const client = new ApiClient(BASE_URL, { token: () => "private-token" });
    await expect(client.request("/tasks/task-id", { method: "PATCH", body: { due_date: null } }))
      .resolves.toEqual({ id: "task-id" });
  });

  it("sends password form data without an old session's authorization", async () => {
    server.use(http.post(`${BASE_URL}/auth/login`, async ({ request }) => {
      expect(request.headers.get("Authorization")).toBeNull();
      expect(request.headers.get("Content-Type")).toContain("application/x-www-form-urlencoded");
      expect(await request.text()).toBe("username=a%40example.test&password=private-password");
      return HttpResponse.json({ access_token: "new-token", token_type: "bearer" });
    }));
    const client = new ApiClient(BASE_URL, { token: () => "old-token" });
    await expect(client.request("/auth/login", {
      method: "POST", authenticated: false,
      body: new URLSearchParams({ username: "a@example.test", password: "private-password" }),
    })).resolves.toEqual({ access_token: "new-token", token_type: "bearer" });
  });

  it("accepts a bodyless deletion response", async () => {
    server.use(http.delete(`${BASE_URL}/tasks/task-id`, () => new HttpResponse(null, { status: 204 })));
    await expect(new ApiClient(BASE_URL).request("/tasks/task-id", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("uploads multipart and downloads authenticated bytes without credential URLs", async () => {
    server.use(
      http.post(`${BASE_URL}/files`, async ({ request }) => {
        expect(request.headers.get("Content-Type")).toContain("multipart/form-data; boundary=");
        const form = await request.formData();
        expect(form.get("file")).toBeInstanceOf(File);
        return HttpResponse.json({ id: "file-id" });
      }),
      http.get(`${BASE_URL}/content`, ({ request }) => {
        expect(request.headers.get("Authorization")).toBe("Bearer private-token");
        expect(request.url).toBe(`${BASE_URL}/content`);
        return new HttpResponse("%PDF-content", { headers: { "Content-Type": "application/pdf" } });
      }),
    );
    const client = new ApiClient(BASE_URL, { token: () => "private-token" });
    const form = new FormData();
    form.append("file", new File(["%PDF-content"], "test.pdf", { type: "application/pdf" }));
    await expect(client.request("/files", { method: "POST", body: form })).resolves.toEqual({ id: "file-id" });
    const blob = await client.download("/content");
    expect(blob.type).toBe("application/pdf");
    expect(await blob.text()).toBe("%PDF-content");
  });

  it("preserves Retry-After seconds without retrying mutations automatically", async () => {
    const handler = vi.fn(() => HttpResponse.json({ detail: "Slow down" }, {
      status: 429, headers: { "Retry-After": "10" },
    }));
    server.use(http.post(`${BASE_URL}/jobs`, handler));
    const error = await captureError(new ApiClient(BASE_URL).request("/jobs", { method: "POST" }));
    expect(error.retryAfterSeconds).toBe(10);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it.each(["garbage", "-1", "Infinity"])("ignores invalid Retry-After %s", async (value) => {
    server.use(http.get(`${BASE_URL}/thing`, () => HttpResponse.json({}, {
      status: 429, headers: { "Retry-After": value },
    })));
    expect((await captureError(new ApiClient(BASE_URL).get("/thing"))).retryAfterSeconds).toBeNull();
  });

  it("notifies expiry only for the session that sent an authenticated request", async () => {
    let token = "old-token";
    const unauthorized = vi.fn();
    server.use(http.get(`${BASE_URL}/thing`, () => {
      token = "new-token";
      return HttpResponse.json({ detail: "Expired" }, { status: 401 });
    }));
    const client = new ApiClient(BASE_URL, { token: () => token, unauthorized });
    await captureError(client.get("/thing"));
    expect(unauthorized).not.toHaveBeenCalled();
    server.use(http.get(`${BASE_URL}/thing`, () => HttpResponse.json({ detail: "Expired" }, { status: 401 })));
    await captureError(client.get("/thing"));
    expect(unauthorized).toHaveBeenCalledTimes(1);
    await captureError(client.request("/thing", { authenticated: false }));
    expect(unauthorized).toHaveBeenCalledTimes(1);
  });

  it("does not retain credential error bodies or sensitive request URLs in errors", async () => {
    server.use(http.post(`${BASE_URL}/auth/sso/exchange`, () => HttpResponse.json({
      detail: "private-code", access_token: "private-token",
    }, { status: 401 })));
    const error = await captureError(new ApiClient(BASE_URL).request("/auth/sso/exchange", {
      method: "POST", authenticated: false, body: { code: "private-code" },
    }));
    expect(error.body).toBeUndefined();
    expect(String(error)).not.toContain("private-code");
    expect(String(error)).not.toContain("private-token");
    expect(error.cause).toBeUndefined();
  });

  it("refuses queued work from a previous session before it reaches the network", async () => {
    let version = 1;
    const handler = vi.fn(() => HttpResponse.json({}));
    server.use(http.post(`${BASE_URL}/tasks`, handler));
    const client = new ApiClient(BASE_URL, { token: () => "new-user-token", version: () => version, expectedVersion: 1 });
    version = 2;
    await expect(client.request("/tasks", { method: "POST", body: { title: "old-user-edit" } })).rejects.toMatchObject({ kind: "session" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("returns the parsed JSON body on a 2xx response", async () => {
    server.use(http.get(`${BASE_URL}/thing`, () => HttpResponse.json({ value: 42 })));

    await expect(new ApiClient(BASE_URL).get("/thing")).resolves.toEqual({ value: 42 });
  });

  it("throws ApiError carrying the status and parsed body on a non-2xx response", async () => {
    server.use(
      http.get(`${BASE_URL}/thing`, () => HttpResponse.json({ detail: "down" }, { status: 503 })),
    );

    const error = await captureError(new ApiClient(BASE_URL).get("/thing"));

    expect(error.kind).toBe("http");
    expect(error.status).toBe(503);
    expect(error.body).toEqual({ detail: "down" });
  });

  it("throws ApiError with an undefined body when a non-2xx response is not JSON", async () => {
    server.use(
      http.get(`${BASE_URL}/thing`, () => new HttpResponse("<h1>Bad gateway</h1>", { status: 502 })),
    );

    const error = await captureError(new ApiClient(BASE_URL).get("/thing"));

    expect(error.status).toBe(502);
    expect(error.body).toBeUndefined();
  });

  it("throws ApiError marked as a network failure when the request cannot be made", async () => {
    server.use(http.get(`${BASE_URL}/thing`, () => HttpResponse.error()));

    const error = await captureError(new ApiClient(BASE_URL).get("/thing"));

    expect(error.kind).toBe("network");
    expect(error.status).toBeNull();
  });

  it("throws ApiError when a 2xx response body is not valid JSON", async () => {
    server.use(http.get(`${BASE_URL}/thing`, () => new HttpResponse("not json", { status: 200 })));

    const error = await captureError(new ApiClient(BASE_URL).get("/thing"));

    expect(error.kind).toBe("http");
    expect(error.status).toBe(200);
  });
});
