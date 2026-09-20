import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { Providers, useAuthService } from "@/app/providers";
import { server } from "@/test/server";
import { apiPerson } from "@/test/httpFixtures";
import { AuthBoundary } from "./AuthBoundary";
const base = "http://localhost:8000";
function Private() {
  const auth = useAuthService();
  return <button onClick={() => auth?.logout()}>Private workspace: sign out</button>;
}
function renderApp(providerStatus = 200) {
  server.use(http.get(`${base}/auth/sso/providers`, () => HttpResponse.json({ providers: [] }, { status: providerStatus })));
  return render(<Providers><AuthBoundary><Private /></AuthBoundary></Providers>);
}
function fill() {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "test@example.test" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password" } });
}
describe("verified cookie auth screen", () => {
  it("signs in through HTTP, signs out, and verifies the persisted session on a full remount", async () => {
    let signedIn = false;
    server.use(
      http.get(`${base}/auth/session`, () => signedIn ? HttpResponse.json(apiPerson) : new HttpResponse(null, { status: 401 })),
      http.post(`${base}/auth/session`, () => { signedIn = true; return HttpResponse.json(apiPerson); }),
      http.delete(`${base}/auth/session`, () => { signedIn = false; return new HttpResponse(null, { status: 204 }); }),
    );
    const view = renderApp();
    expect(screen.queryByText(/Private workspace/)).not.toBeInTheDocument();
    expect(await screen.findByText(/stay signed in across reloads/i)).toBeInTheDocument();
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.click(await screen.findByRole("button", { name: /Private workspace/ }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("button", { name: /Private workspace/ });
    view.unmount();
    renderApp();
    expect(screen.queryByRole("heading", { name: "Welcome back" })).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Private workspace/ })).toBeInTheDocument();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("registers with a name and safely presents a duplicate email error with retry", async () => {
    server.use(http.get(`${base}/auth/session`, () => new HttpResponse(null, { status: 401 })), http.post(`${base}/auth/register`, () => HttpResponse.json({}, { status: 409 })));
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "Create an account" }));
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Test Person" } });
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already registered/i);
    expect(screen.getByRole("button", { name: "Create account" })).toBeEnabled();
  });

  it("shows provider discovery errors without blocking password sign-in", async () => {
    server.use(http.get(`${base}/auth/session`, () => new HttpResponse(null, { status: 401 })));
    renderApp(503);
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry single sign-on" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });
});
