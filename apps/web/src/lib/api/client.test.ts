import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
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
