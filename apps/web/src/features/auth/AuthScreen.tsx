"use client";

import { Check } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useAuthService, useSession } from "@/app/providers";
import { Button } from "@/components/ui/Button";
import type { AuthService } from "./types";

export function SessionCheck() {
  const auth = useAuthService();
  const session = useSession();
  const unavailable = session.status === "unavailable";
  const logoutFailed = session.status === "logout-failed";
  return <main className="grid min-h-dvh place-items-center bg-bg px-5 text-fg"><section className="rounded-bt border border-line bg-panel p-7">
    <p role={unavailable || logoutFailed ? "alert" : "status"}>{unavailable ? "We could not verify your session. Check your connection and try again." : logoutFailed ? "Sign-out could not reach the server. Retry to remove this browser's session." : session.status === "signing-out" ? "Signing out…" : "Checking your session…"}</p>
    {(unavailable || logoutFailed) && <Button className="mt-4" onClick={() => { if (logoutFailed) void auth?.logout(); else void auth?.restore?.(); }}>Retry {logoutFailed ? "sign out" : "session check"}</Button>}
  </section></main>;
}

export function AuthScreen({ auth, expired, mode, onModeChange, onSso }: { auth: AuthService; expired: boolean; mode?: "login" | "register"; onModeChange?: () => void; onSso?: () => void }) {
  const [localRegister, setRegister] = useState(false);
  const register = mode ? mode === "register" : localRegister;
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [providers, setProviders] = useState<{ name: string; url: string }[]>([]);
  const [providerError, setProviderError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    auth.providers().then((providers) => {
      if (live) { setProviders(providers); setProviderError(false); }
    }).catch(() => { if (live) setProviderError(true); });
    return () => { live = false; };
  }, [auth, attempt]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setError("");
    setPending(true);
    try {
      if (register) await auth.register(email, name, password);
      else await auth.login(email, password);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Sign-in failed. Please try again.");
    } finally {
      setPassword("");
      setPending(false);
    }
  }

  const field = "mt-1.5 h-11 w-full rounded-bt border border-line bg-card px-3 text-[14px] text-fg placeholder:text-fg-3 focus:border-acc";
  return (
    <main className="grid min-h-dvh place-items-center bg-bg px-5 py-10">
      <section aria-labelledby="auth-title" className="w-full max-w-[420px] animate-bt-in rounded-bt border border-line bg-panel p-7 shadow-2 max-sm:p-5">
        <div className="mb-9 flex items-center gap-2.5 font-heading text-[18px] text-fg">
          <span className="grid size-7 place-items-center rounded-bt-sm bg-acc text-acc-fg shadow-glow"><Check aria-hidden="true" size={16} strokeWidth={3} /></span>
          Ballast <span className="font-sans text-[14px] text-fg-3">Tasks</span>
        </div>
        <p className="mb-2 font-mono text-[10.5px] tracking-[.1em] text-acc uppercase">Your work, in focus</p>
        <h1 id="auth-title" className="font-heading text-[26px] font-semibold text-fg">{register ? "Create your account" : "Welcome back"}</h1>
        <p className="mt-2 text-[13px] text-fg-3">{register ? "A place for the work that matters." : "Sign in to your shared workspace."}</p>
        {expired && <p role="status" className="mt-4 text-[13px] text-warn">Your session expired. Sign in again to continue.</p>}
        <form className="mt-7 flex flex-col gap-4" onSubmit={(event) => { void submit(event); }}>
          {register && <label className="text-[12px] text-fg-2">Full name<input id="auth-name" name="name" autoComplete="name" required maxLength={200} value={name} disabled={pending} onChange={(event) => setName(event.target.value)} className={field} /></label>}
          <label className="text-[12px] text-fg-2">Email<input id="auth-email" name="email" type="email" autoComplete="username" required value={email} disabled={pending} onChange={(event) => setEmail(event.target.value)} className={field} /></label>
          <label className="text-[12px] text-fg-2">Password<input id="auth-password" name="password" type="password" autoComplete={register ? "new-password" : "current-password"} required minLength={register ? 8 : undefined} maxLength={128} value={password} disabled={pending} onChange={(event) => setPassword(event.target.value)} className={field} /></label>
          {error && <p role="alert" className="text-[13px] text-danger">{error}</p>}
          <Button type="submit" disabled={pending} className="mt-2 h-11 justify-center disabled:cursor-wait disabled:opacity-60">{pending ? "Please wait…" : register ? "Create account" : "Sign in"}</Button>
        </form>
        {providers.map((provider) => <a key={provider.name} href={provider.url} onClick={onSso} className="mt-3 flex min-h-11 items-center justify-center rounded-bt border border-line text-[13px] text-fg-2 hover:bg-card">Continue with {provider.name}</a>)}
        {providerError && <div className="mt-3 text-[12px] text-fg-3">Single sign-on is unavailable. <Button variant="ghost" onClick={() => setAttempt((n) => n + 1)}>Retry single sign-on</Button></div>}
        <Button variant="ghost" disabled={pending} className="mt-5 w-full justify-center" onClick={() => { if (onModeChange) onModeChange(); else setRegister(!register); setError(""); setPassword(""); }}>{register ? "Already have an account? Sign in" : "Create an account"}</Button>
        <p className="mt-6 border-t border-line pt-4 text-[11px] leading-relaxed text-fg-3">Stay signed in across reloads and tabs until your session expires or you sign out. Your saved work stays in the workspace.</p>
      </section>
    </main>
  );
}
