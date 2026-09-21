// @vitest-environment node
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { ApiClient } from "@/lib/api/client";
import { server } from "@/test/server";
import { apiPerson } from "@/test/httpFixtures";
import { HttpAuthService } from "./service";

const base = "http://browser-auth.test";
function setup() {
  const client: ApiClient = new ApiClient(base, { browser: true, token: () => auth.token(), version: () => auth.current().epoch, unauthorized: () => auth.expire() });
  const auth = new HttpAuthService(client, base, true);
  return { auth, client };
}
describe("verified persistent browser session", () => {
  it("waits for bootstrap, restores without a bearer and never stores a credential", async () => {
    const { auth } = setup();
    expect(auth.current().status).toBe("checking");
    server.use(http.get(`${base}/auth/session`, ({ request }) => {
      expect(request.credentials).toBe("include");
      expect(request.headers.get("Authorization")).toBeNull();
      return HttpResponse.json(apiPerson);
    }));
    await auth.restore();
    expect(auth.current().user?.name).toBe(apiPerson.full_name);
    expect(auth.token()).toBeNull();
    const nextTab = setup().auth;
    await nextTab.restore();
    expect(nextTab.current().user?.id).toBe(apiPerson.id);
  });
  it("changes the epoch when another tab changes the verified identity", async () => {
    const { auth, client } = setup();
    server.use(http.get(`${base}/auth/session`, () => HttpResponse.json(apiPerson)));
    await auth.restore();
    const epoch = auth.current().epoch;
    let release!: () => void;
    let started!: () => void;
    const ready = new Promise<void>(r => { started = r; });
    const wait = new Promise<void>(r => { release = r; });
    server.use(http.get(`${base}/slow`, async () => { started(); await wait; return HttpResponse.json({ oldUser: true }); }));
    const late = client.get("/slow");
    const settled = late.then(() => "accepted", () => "fenced");
    await ready;
    server.use(http.get(`${base}/auth/session`, () => HttpResponse.json({ ...apiPerson, id: "new-user", full_name: "New User" })));
    await auth.restore();
    release();
    expect(await settled).toBe("fenced");
    expect(auth.current().epoch).toBeGreaterThan(epoch);
    expect(auth.current().user?.id).toBe("new-user");
  });
  it("distinguishes offline/503 from definitive 401", async () => {
    const { auth } = setup();
    server.use(http.get(`${base}/auth/session`, () => new HttpResponse(null, { status: 503 })));
    await auth.restore();
    expect(auth.current()).toMatchObject({ status: "unavailable", user: null });
    server.use(http.get(`${base}/auth/session`, () => new HttpResponse(null, { status: 401 })));
    await auth.restore();
    expect(auth.current()).toMatchObject({ status: "ready", user: null });
  });
  it("posts CSRF protection, signs out on cookie 401 and fences late data", async () => {
    const { auth, client } = setup();
    server.use(http.post(`${base}/auth/session`, ({ request }) => {
      expect(request.headers.get("X-CSRF-Protection")).toBe("1");
      return HttpResponse.json(apiPerson);
    }));
    await auth.login("test@example.test", "synthetic-password");
    let release!: () => void;
    let started!: () => void;
    const ready = new Promise<void>(r => { started = r; });
    const wait = new Promise<void>(r => { release = r; });
    server.use(http.get(`${base}/slow`, async () => { started(); await wait; return HttpResponse.json({ private: true }); }), http.get(`${base}/expired`, () => new HttpResponse(null, { status: 401 })));
    const late = client.get("/slow");
    const rejected = expect(late).rejects.toMatchObject({ kind: "session" });
    await ready;
    await expect(client.get("/expired")).rejects.toMatchObject({ status: 401 });
    release(); await rejected;
    expect(auth.current().user).toBeNull();
  });
  it("deletes the cookie after an in-flight login settles, preventing resurrection on reload", async () => {
    const { auth } = setup();
    let release!: () => void;
    let started!: () => void;
    const ready = new Promise<void>(r => { started = r; });
    const wait = new Promise<void>(r => { release = r; });
    const order: string[] = [];
    server.use(http.post(`${base}/auth/session`, async () => { started(); await wait; order.push("cookie issued"); return HttpResponse.json(apiPerson); }), http.delete(`${base}/auth/session`, () => { order.push("cookie deleted"); return new HttpResponse(null, { status: 204 }); }));
    const login = auth.login("test@example.test", "synthetic-password");
    const rejected = expect(login).rejects.toThrow();
    await ready;
    const logout = auth.logout();
    expect(auth.current().user).toBeNull();
    release(); await rejected; await logout;
    expect(order).toEqual(["cookie issued", "cookie deleted"]);
    expect(auth.current()).toMatchObject({ user: null, status: "ready" });
  });
});
