// @vitest-environment node
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { ApiClient } from "@/lib/api/client";
import { server } from "@/test/server";
import { HttpAuthService } from "./service";

const base = "http://auth.test";
const user = { id: "u1", full_name: "Test Person", initials: "TP", role_label: null, email: "test@example.test", is_active: true, created_at: "2026-09-19T00:00:00Z" };
function setup() {
  const client: ApiClient = new ApiClient(base, {
    token: () => auth.token(), version: () => auth.current().epoch, unauthorized: () => auth.expire(),
  });
  const auth = new HttpAuthService(client, base);
  server.use(
    http.post(`${base}/auth/login`, () => HttpResponse.json({ access_token: "test-token", token_type: "bearer" })),
    http.get(`${base}/auth/me`, ({ request }) => {
      expect(request.headers.get("Authorization")).toBe("Bearer test-token");
      return HttpResponse.json(user);
    }),
  );
  return { auth, client };
}

describe("HTTP memory-only authentication", () => {
  it("logs in, reads the caller and clears credentials/state on logout and reconstruction", async () => {
    const { auth } = setup();
    const states: string[] = [];
    const unsubscribe = auth.subscribe(() => states.push(auth.current().user?.name ?? "anonymous"));
    await auth.login("test@example.test", "password");
    expect(auth.current().user).toEqual({ id: "u1", name: "Test Person", initials: "TP", role: "" });
    expect(auth.token()).toBe("test-token");
    auth.logout();
    expect(auth.token()).toBeNull();
    expect(auth.current().user).toBeNull();
    expect(states).toContain("Test Person");
    unsubscribe();
    expect(setup().auth.current().user).toBeNull();
  });

  it("registers then authenticates via the password endpoint, not a fake session", async () => {
    const { auth } = setup();
    server.use(http.post(`${base}/auth/register`, async ({ request }) => {
      expect(await request.json()).toEqual({ email: "test@example.test", full_name: "Test Person", password: "password" });
      expect(request.headers.get("Authorization")).toBeNull();
      return HttpResponse.json(user, { status: 201 });
    }));
    await auth.register("test@example.test", "Test Person", "password");
    expect(auth.current().user?.id).toBe("u1");
  });

  it("does not authenticate after a rejected login and presents only a safe error", async () => {
    const { auth } = setup();
    server.use(http.post(`${base}/auth/login`, () => HttpResponse.json({ detail: "secret" }, { status: 401 })));
    await expect(auth.login("test@example.test", "bad")).rejects.toThrow("Email or password was not accepted");
    expect(auth.token()).toBeNull();
    expect(auth.current().user).toBeNull();
  });

  it("expires on authenticated 401, rejecting subsequent late successful responses", async () => {
    const { auth, client } = setup();
    await auth.login("test@example.test", "password");
    let release!: () => void;
    const wait = new Promise<void>((resolve) => { release = resolve; });
    let started!: () => void;
    const ready = new Promise<void>((resolve) => { started = resolve; });
    server.use(
      http.get(`${base}/slow`, async () => { started(); await wait; return HttpResponse.json({ private: true }); }),
      http.get(`${base}/expired`, () => new HttpResponse(null, { status: 401 })),
    );
    const late = client.get("/slow");
    const rejection = expect(late).rejects.toThrow("session");
    await ready;
    await expect(client.get("/expired")).rejects.toMatchObject({ status: 401 });
    expect(auth.current().reason).toBe("expired");
    release();
    await rejection;
    expect(auth.token()).toBeNull();
  });

  it("does not resurrect a login that resolves after logout", async () => {
    const { auth } = setup();
    let release!: () => void;
    let started!: () => void;
    const wait = new Promise<void>((resolve) => { release = resolve; });
    const ready = new Promise<void>((resolve) => { started = resolve; });
    server.use(http.post(`${base}/auth/login`, async () => {
      started(); await wait;
      return HttpResponse.json({ access_token: "late-token", token_type: "bearer" });
    }));
    const pending = auth.login("test@example.test", "password");
    const rejection = expect(pending).rejects.toThrow();
    await ready;
    auth.logout();
    release();
    await rejection;
    expect(auth.token()).toBeNull();
    expect(auth.current().user).toBeNull();
  });

  it("lists configured providers and exchanges a one-time code in a POST body", async () => {
    const { auth } = setup();
    server.use(
      http.get(`${base}/auth/sso/providers`, () => HttpResponse.json({ providers: [{ name: "fake" }] })),
      http.post(`${base}/auth/sso/exchange`, async ({ request }) => {
        expect(request.url).toBe(`${base}/auth/sso/exchange`);
        expect(await request.json()).toEqual({ code: "one-time" });
        return HttpResponse.json({ access_token: "test-token", token_type: "bearer" });
      }),
    );
    expect(await auth.providers()).toEqual([{ name: "fake", url: `${base}/auth/sso/fake/start` }]);
    await auth.exchange("one-time");
    expect(auth.current().user?.id).toBe("u1");
  });
});
