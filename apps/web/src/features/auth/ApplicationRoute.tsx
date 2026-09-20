"use client";

import { Fragment, Suspense, useCallback, useEffect, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useAuthService, useSession } from "@/app/providers";
import { TasksApp } from "@/features/tasks/shell/TasksApp";
import { TaskRouteContext } from "@/features/tasks/workspace/TaskRouteContext";
import { isTaskPath, parseTaskRoute, returnDestination, taskHref, type TaskRoute } from "@/features/tasks/workspace/route";
import { AuthScreen, SessionCheck } from "./AuthBoundary";

export const SSO_RETURN_KEY = "bt-sso-return";

export function ApplicationRoute() {
  return <Suspense fallback={<SessionCheck />}><Route /></Suspense>;
}
function Route() {
  const auth = useAuthService();
  const session = useSession();
  const pathname = usePathname();
  const params = useSearchParams();
  const router = useRouter();
  const anonymous = pathname === "/login" || pathname === "/register";
  const href = `${pathname}${params.size ? `?${params}` : ""}`;
  const destination = returnDestination(params.get("returnTo"));
  const ready = !auth || !session.status || session.status === "ready";
  const signedIn = !auth || !!session.user;
  const valid = isTaskPath(pathname, !auth);
  const route = useMemo(() => parseTaskRoute(href, !auth), [href, auth]);
  const navigate = useCallback((next: TaskRoute, replace = false) => {
    const target = taskHref(next);
    if (target === `${window.location.pathname}${window.location.search}`) return;
    // The native history integration avoids server navigations/remounting drafts for query
    // changes. Search replaces the current entry; filters/pages add a Back/Forward step.
    window.history[replace ? "replaceState" : "pushState"](null, "", target);
  }, []);
  const navigation = useMemo(() => ({ route, navigate }), [route, navigate]);
  useEffect(() => {
    if (!ready) return;
    if (!signedIn && !anonymous) router.replace(`/login?returnTo=${encodeURIComponent(returnDestination(href))}`);
    else if (signedIn && (anonymous || pathname === "/")) router.replace(anonymous ? destination : "/tasks");
    else if (signedIn && valid && href !== taskHref(route)) navigate(route, true);
  }, [ready, signedIn, anonymous, router, href, destination, pathname, valid, route, navigate]);
  if (!ready) return <SessionCheck />;
  if (!signedIn && anonymous && auth) return <AuthScreen key={pathname} auth={auth} expired={session.reason === "expired"} mode={pathname === "/register" ? "register" : "login"} onModeChange={() => router.push(`${pathname === "/register" ? "/login" : "/register"}?returnTo=${encodeURIComponent(destination)}`)} onSso={() => sessionStorage.setItem(SSO_RETURN_KEY, destination)} />;
  if (!signedIn || anonymous || pathname === "/") return <SessionCheck />;
  if (!valid) return <main className="p-7 text-fg"><h1>Page not found</h1><a href="/tasks">All tasks</a></main>;
  return <Fragment key={session.epoch}><TaskRouteContext.Provider value={navigation}><TasksApp /></TaskRouteContext.Provider></Fragment>;
}
