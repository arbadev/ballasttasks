import { ApiError, type HttpTransport } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { AuthService, Session } from "./types";

type Schemas = components["schemas"];

/** Browser sessions are server-set cookies. Only the legacy bearer transport holds a token. */
export class HttpAuthService implements AuthService {
  #token: string | null = null;
  private snapshot: Session = { epoch: 0, user: null };
  private listeners = new Set<() => void>();

  private pendingAuth: Promise<void> | null = null;
  private restoring: Promise<void> | null = null;
  private channel: BroadcastChannel | null = null;

  constructor(private readonly client: HttpTransport, private readonly apiUrl: string, private readonly browser = false) {
    if (browser) this.snapshot = { epoch: 0, user: null, status: "checking" };
  }

  /** No tokens, users or login flags are sent between tabs. Every positive check is server-validated. */
  connect = (): (() => void) => {
    if (!this.browser) return () => {};
    this.channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel("bt-session");
    if (this.channel) this.channel.onmessage = (event) => {
      if (event.data === "logout") void this.signOut(false);
      else if (event.data === "expired") this.clear("expired");
      else if (event.data === "changed") {
        const pending = [this.pendingAuth, this.restoring];
        this.clear(undefined, "checking");
        void Promise.allSettled(pending).then(() => this.restore());
      }
    };
    const check = () => { if (!document.hidden) void this.restore(); };
    window.addEventListener("focus", check);
    window.addEventListener("pageshow", check);
    const timer = setInterval(check, 60_000);
    void this.restore();
    return () => { clearInterval(timer); window.removeEventListener("focus", check); window.removeEventListener("pageshow", check); this.channel?.close(); this.channel = null; };
  };

  restore = (): Promise<void> => {
    if (!this.browser || this.pendingAuth || this.snapshot.status === "signing-out" || this.snapshot.status === "logout-failed") return Promise.resolve();
    if (this.restoring) return this.restoring;
    const epoch = this.snapshot.epoch;
    this.restoring = this.client.request<Schemas["UserResponse"] | null>("/auth/session", { authenticated: false }).then((user) => {
      this.assertCurrent(epoch);
      if (user) this.accept(user, epoch);
      else this.clear(this.snapshot.user ? "expired" : undefined);
    }).catch((error: unknown) => {
      if (epoch !== this.snapshot.epoch) return;
      if (error instanceof ApiError && error.status === 401) this.clear(this.snapshot.user ? "expired" : undefined);
      else { this.snapshot = { ...this.snapshot, status: "unavailable" }; this.emit(); }
    }).finally(() => { this.restoring = null; });
    return this.restoring;
  };

  token = (): string | null => this.#token;
  current = (): Session => this.snapshot;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  logout = (): Promise<void> => this.signOut(true);

  private async signOut(broadcast: boolean): Promise<void> {
    if (this.snapshot.status === "signing-out") return;
    const pending = this.pendingAuth;
    this.clear(undefined, this.browser ? "signing-out" : "ready");
    if (broadcast) this.channel?.postMessage("logout");
    if (!this.browser) return;
    // Fetch epoch fencing cannot undo a Set-Cookie already accepted by the browser.
    // Delete AFTER any outstanding credential response, and block another sign-in meanwhile.
    await pending?.catch(() => {});
    try {
      await this.client.request("/auth/session", { method: "DELETE", authenticated: false });
      this.clear();
    } catch {
      this.snapshot = { ...this.snapshot, status: "logout-failed" }; this.emit();
    }
  }
  expire = (): void => { this.clear("expired"); this.channel?.postMessage("expired"); };

  async login(email: string, password: string): Promise<void> {
    if (this.browser) return this.browserAuthenticate(() => this.client.request<Schemas["UserResponse"]>("/auth/session", {
      method: "POST", authenticated: false, body: new URLSearchParams({ username: email, password }),
    }));
    await this.authenticate(() => this.client.request<Schemas["TokenResponse"]>("/auth/login", {
      method: "POST", authenticated: false, body: new URLSearchParams({ username: email, password }),
    }));
  }

  async register(email: string, name: string, password: string): Promise<void> {
    if (this.browser) return this.browserAuthenticate(async () => {
      await this.client.request("/auth/register", { method: "POST", authenticated: false, body: { email, full_name: name, password } });
      return this.client.request<Schemas["UserResponse"]>("/auth/session", { method: "POST", authenticated: false, body: new URLSearchParams({ username: email, password }) });
    });
    await this.authenticate(async () => {
      await this.client.request<Schemas["UserResponse"]>("/auth/register", {
        method: "POST", authenticated: false,
        body: { email, full_name: name, password } satisfies Schemas["RegisterRequest"],
      });
      return this.client.request<Schemas["TokenResponse"]>("/auth/login", {
        method: "POST", authenticated: false, body: new URLSearchParams({ username: email, password }),
      });
    });
  }

  async exchange(code: string): Promise<void> {
    if (this.browser) return this.browserAuthenticate(() => this.client.request<Schemas["UserResponse"]>("/auth/session/sso", { method: "POST", authenticated: false, body: { code } }));
    await this.authenticate(() => this.client.request<Schemas["TokenResponse"]>("/auth/sso/exchange", {
      method: "POST", authenticated: false, body: { code },
    }));
  }

  async providers(): Promise<{ name: string; url: string }[]> {
    const result = await this.client.request<Schemas["SsoProvidersResponse"]>("/auth/sso/providers", { authenticated: false });
    return result.providers.map(({ name }) => ({ name, url: `${this.apiUrl}/auth/sso/${encodeURIComponent(name)}/start` }));
  }

  private async authenticate(issue: () => Promise<Schemas["TokenResponse"]>): Promise<void> {
    this.clear();
    const epoch = this.snapshot.epoch;
    try {
      const issued = await issue();
      this.assertCurrent(epoch);
      this.#token = issued.access_token;
      const user = await this.client.get<Schemas["UserResponse"]>("/auth/me");
      this.assertCurrent(epoch);
      this.snapshot = { epoch, user: { id: user.id, name: user.full_name, initials: user.initials, role: user.role_label ?? "" } };
      this.emit();
    } catch (error) {
      if (epoch === this.snapshot.epoch) this.clear();
      if (error instanceof ApiError) {
        if (error.status === 401) throw new Error("Email or password was not accepted, or the sign-in link expired.");
        if (error.status === 409) throw new Error("That email is already registered. Sign in instead.");
        if (error.status === 422) throw new Error("Check your name, email and password (8–128 characters).");
        if (error.status === 429) throw new Error(`Too many attempts. Try again in ${error.retryAfterSeconds ?? 60} seconds.`);
      }
      throw new Error("Sign-in could not be completed. Please try again.");
    }
  }

  private accept(user: Schemas["UserResponse"], epoch: number): void {
    // The cookie can change in another tab. A different server-verified identity must
    // retire old services/drafts just as surely as an explicit local sign-out does.
    if (this.snapshot.user && this.snapshot.user.id !== user.id) epoch += 1;
    this.snapshot = { epoch, status: "ready", user: { id: user.id, name: user.full_name, initials: user.initials, role: user.role_label ?? "" } };
    this.emit();
  }

  private async browserAuthenticate(issue: () => Promise<Schemas["UserResponse"]>): Promise<void> {
    if (this.pendingAuth || this.snapshot.status === "signing-out" || this.snapshot.status === "logout-failed") throw new Error("Finish signing out before signing in.");
    this.clear();
    const epoch = this.snapshot.epoch;
    const operation = (async () => {
      try { const user = await issue(); this.assertCurrent(epoch); this.accept(user, epoch); this.channel?.postMessage("changed"); }
      catch (error) {
        if (epoch === this.snapshot.epoch) this.clear();
        if (error instanceof ApiError) {
          if (error.status === 401) throw new Error("Email or password was not accepted, or the sign-in link expired.");
          if (error.status === 409) throw new Error("That email is already registered. Sign in instead.");
          if (error.status === 422) throw new Error("Check your name, email and password (8–128 characters).");
          if (error.status === 429) throw new Error(`Too many attempts. Try again in ${error.retryAfterSeconds ?? 60} seconds.`);
        }
        throw new Error("Sign-in could not be completed. Please try again.");
      }
    })();
    this.pendingAuth = operation;
    try { await operation; } finally { if (this.pendingAuth === operation) this.pendingAuth = null; }
  }

  private assertCurrent(epoch: number): void {
    if (epoch !== this.snapshot.epoch) throw new Error("This session has ended.");
  }

  private clear(reason?: "expired", status: Session["status"] = "ready"): void {
    this.#token = null;
    this.snapshot = { epoch: this.snapshot.epoch + 1, user: null, reason, status };
    this.emit();
  }

  private emit(): void { for (const listener of this.listeners) listener(); }
}
