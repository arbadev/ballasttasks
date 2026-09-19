"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthService } from "@/app/providers";
import { Button } from "@/components/ui/Button";

export function AuthCallback() {
  const auth = useAuthService();
  const router = useRouter();
  const started = useRef(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    // No code survives into subsequent navigation, referrers or screenshots.
    window.history.replaceState(null, "", "/auth/callback");
    async function exchange() {
      if (!code || params.has("error") || !auth) throw new Error("Could not complete single sign-on. Please sign in again.");
      await auth.exchange(code);
      router.replace("/");
    }
    void exchange().catch((error: unknown) => setError(error instanceof Error ? error.message : "Could not complete single sign-on."));
  }, [auth, router]);
  return <main className="grid min-h-dvh place-items-center bg-bg px-5">
    <section className="w-full max-w-[420px] rounded-bt border border-line bg-panel p-7 shadow-2">
      <h1 className="font-heading text-[24px] text-fg">Signing in</h1>
      {error ? <p role="alert" className="mt-4 text-[13px] text-danger">{error}</p> : <p role="status" className="mt-4 text-[13px] text-fg-3">Completing your sign-in…</p>}
      <Button variant="ghost" className="mt-5" onClick={() => { auth?.logout(); router.replace("/"); }}>Back to sign in</Button>
    </section>
  </main>;
}
