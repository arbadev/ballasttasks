import { ApiError, type HttpTransport } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { AuthService, Session } from "./types";

type Schemas = components["schemas"];

/** Memory only. A reload deliberately creates an anonymous session. Never serialize this service. */
export class HttpAuthService implements AuthService {
  #token: string | null = null;
  private snapshot: Session = { epoch: 0, user: null };
  private listeners = new Set<() => void>();

  constructor(private readonly client: HttpTransport, private readonly apiUrl: string) {}

  token = (): string | null => this.#token;
  current = (): Session => this.snapshot;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  logout = (): void => { this.clear(); };
  expire = (): void => { this.clear("expired"); };

  async login(email: string, password: string): Promise<void> {
    await this.authenticate(() => this.client.request<Schemas["TokenResponse"]>("/auth/login", {
      method: "POST", authenticated: false, body: new URLSearchParams({ username: email, password }),
    }));
  }

  async register(email: string, name: string, password: string): Promise<void> {
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

  private assertCurrent(epoch: number): void {
    if (epoch !== this.snapshot.epoch) throw new Error("This session has ended.");
  }

  private clear(reason?: "expired"): void {
    this.#token = null;
    this.snapshot = { epoch: this.snapshot.epoch + 1, user: null, reason };
    this.emit();
  }

  private emit(): void { for (const listener of this.listeners) listener(); }
}
