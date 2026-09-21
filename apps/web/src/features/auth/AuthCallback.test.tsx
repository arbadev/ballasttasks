import { render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import type { AuthService } from "./types";
import { AuthCallback } from "./AuthCallback";
const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
afterEach(() => { history.replaceState(null, "", "/"); vi.clearAllMocks(); });
function auth(exchange: AuthService["exchange"]): AuthService {
  const session = { epoch: 0, user: null };
  return { current: () => session, subscribe: () => () => {}, login: vi.fn(), register: vi.fn(), exchange, providers: vi.fn(), logout: vi.fn() };
}
describe("SSO callback", () => {
  it("removes the one-time code before exchange and exchanges once in StrictMode", async () => {
    history.replaceState(null, "", "/auth/callback?code=one-time&next=https://evil.test");
    const exchange = vi.fn(async (code: string) => {
      expect(location.search).toBe("");
      expect(code).toBe("one-time");
    });
    render(<StrictMode><Providers authService={auth(exchange)}><AuthCallback /></Providers></StrictMode>);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/tasks"));
    expect(exchange).toHaveBeenCalledTimes(1);
    expect(document.body).not.toHaveTextContent("one-time");
  });
  it("presents a safe callback error without displaying untrusted query content", async () => {
    history.replaceState(null, "", "/auth/callback?error=private-provider-detail");
    const exchange = vi.fn();
    render(<Providers authService={auth(exchange)}><AuthCallback /></Providers>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not complete/i);
    expect(document.body).not.toHaveTextContent("private-provider-detail");
    expect(location.search).toBe("");
    expect(exchange).not.toHaveBeenCalled();
  });
});
