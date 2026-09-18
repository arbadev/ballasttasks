"use client";

import { useEffect, useId, useState } from "react";
import { useHealthService } from "@/app/providers";
import type { HealthViewModel } from "./service";

type State =
  | { phase: "loading" }
  | { phase: "loaded"; health: HealthViewModel }
  | { phase: "error" };

function summary(health: HealthViewModel): string {
  if (!health.apiReachable) return "API is unreachable";
  return health.ready ? "All systems operational" : "Some systems are failing";
}

function StatusRow({ label, ok }: { label: string; ok: boolean }) {
  const id = useId();
  return (
    <li
      aria-labelledby={`${id}-label ${id}-status`}
      className="flex items-center justify-between gap-4 py-3"
    >
      <span id={`${id}-label`} className="font-medium">
        {label}
      </span>
      {/* Status is carried by the text; colour only reinforces it. */}
      <span
        id={`${id}-status`}
        className={`rounded-full px-2.5 py-0.5 text-sm font-medium ${
          ok
            ? "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300"
            : "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300"
        }`}
      >
        {ok ? "OK" : "Failing"}
      </span>
    </li>
  );
}

export function StatusCard() {
  const service = useHealthService();
  const [state, setState] = useState<State>({ phase: "loading" });
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    service.getHealth().then(
      (health) => {
        if (!cancelled) setState({ phase: "loaded", health });
      },
      () => {
        if (!cancelled) setState({ phase: "error" });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [service, reloadToken]);

  const refresh = () => {
    setState({ phase: "loading" });
    setReloadToken((token) => token + 1);
  };

  return (
    <section
      aria-labelledby="status-heading"
      className="w-full max-w-md rounded-xl border border-black/10 p-6 shadow-sm dark:border-white/15"
    >
      <div className="flex items-center justify-between gap-4">
        <h1 id="status-heading" className="text-xl font-semibold">
          System status
        </h1>
        <button
          type="button"
          onClick={refresh}
          disabled={state.phase === "loading"}
          className="rounded-md border border-black/15 px-3 py-1.5 text-sm font-medium hover:bg-black/5 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50 dark:border-white/20 dark:hover:bg-white/10"
        >
          Refresh
        </button>
      </div>

      <p aria-live="polite" className="mt-2 text-sm opacity-80">
        {state.phase === "loading" && "Checking system status…"}
        {state.phase === "loaded" && summary(state.health)}
      </p>

      {state.phase === "error" && (
        <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">
          Could not load system status. Try refreshing.
        </p>
      )}

      {state.phase === "loaded" && (
        <>
          <ul className="mt-4 divide-y divide-black/10 dark:divide-white/15">
            <StatusRow label="API" ok={state.health.apiReachable} />
            {state.health.components.map((component) => (
              <StatusRow key={component.name} label={component.label} ok={component.ok} />
            ))}
          </ul>

          {state.health.ai && (
            <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="opacity-70">AI provider</dt>
              <dd className="font-mono">{state.health.ai.provider}</dd>
              <dt className="opacity-70">AI model</dt>
              <dd className="font-mono">{state.health.ai.model}</dd>
            </dl>
          )}
        </>
      )}
    </section>
  );
}
