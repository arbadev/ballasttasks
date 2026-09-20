# ADR 0009: Persistent browser credentials and URL-owned task navigation

- Status: Accepted
- Date: 2026-09-20
- Supersedes: the memory-only browser-session limitation and the cookie alternative deferred in ADR 0006. Shared-workspace authorization, JWT expiry and bearer clients are unchanged.

## Decision

The browser uses the API's existing signed access token in a server-set `bt_session`
cookie, not a token exposed to JavaScript or a remembered logged-in flag. No refresh
credentials, session database, new identity provider or dependency is introduced.
`POST /auth/session` accepts the password form and returns the current public user;
`POST /auth/session/sso` redeems the existing single-use SSO code and does the same.
Registration remains `POST /auth/register`, followed by password session creation.
The bearer `/auth/login` and `/auth/sso/exchange` contracts remain available to API clients.

`GET /auth/session` verifies the token and re-reads the active user through the existing
authentication seam. It returns a user, `null` when there is no credential, or `401` when
an offered credential is invalid/expired or its user is no longer active. It never
reissues the cookie. The ordinary anonymous check is a successful empty session, not
an HTTP error that fills the browser console. A temporary network/5xx failure is not
an anonymous session: the app withholds workspace data and offers a session-check retry.

Cookie attributes: HttpOnly, SameSite=Lax, Path=/, no Domain, persistent Max-Age equal
to `AUTH__ACCESS_TOKEN_EXPIRE_MINUTES * 60` (default 30 minutes). JWT `exp` remains the
hard server-side deadline even if cookie expiry and token issue time differ slightly.
There is no sliding expiry. Secure is mandatory when `APP__ENV=production`; production
CORS origins must be HTTPS. Development/test HTTP is allowed only for exact loopback
origins. Serve web and API on the same site (including matching `localhost` versus
`127.0.0.1`); cross-site cookie deployment is deliberately unsupported by SameSite=Lax.
Cookie scope is a host, not a port: independent local deployments should use separate
browser profiles/hosts, not assume ports isolate cookies.

### CSRF and bearer compatibility

Every cookie-authenticated unsafe request, including uploads through `StreamingUserId`,
requires **both** an exact configured `Origin` from `CORS__ALLOWED_ORIGINS` and
`X-CSRF-Protection: 1`. The browser session creation/exchange/deletion endpoints require
these checks even before a cookie exists (login CSRF). The custom non-simple header
forces a preflight; server-side Origin validation is also required because CORS alone
is not write protection. Missing/null/foreign origins fail with `403`.

CORS accepts exact HTTPS origins or HTTP loopback origins, never wildcards, paths or
embedded credentials; methods and request headers are enumerated. Explicit Authorization
wins over cookies, including an invalid bearer: there is no fallback to a valid cookie.
Bearer requests remain usable without browser CSRF headers. Feature routes still obtain
only a user id through `CurrentUserId`/`StreamingUserId`; no feature knows JWT details.

### Logout, expiry and races

`DELETE /auth/session` clears the host cookie and works when already anonymous/expired.
The client immediately unmounts session data/drafts and advances its epoch. It waits for
an outstanding credential response before deleting the cookie: ignoring a late JSON
response cannot undo a `Set-Cookie` the browser already accepted. New sign-in is blocked
until deletion succeeds; a failed deletion offers explicit retry instead of claiming
server logout succeeded. Epoch checks fence queued mutations and late responses.

Same-origin tabs exchange only invalidation notifications through BroadcastChannel,
never credentials or users. Logout deletes after each tab's own in-flight sign-in;
a changed sign-in causes server revalidation. Focus/pageshow and a visible-page minute
check also verify the session; a changed verified user advances the epoch and disposes
old services. Unsupported BroadcastChannel clients reconcile on those checks or the
next API response. Expiry is enforced on every API call, with UI detection on a 401,
focus/pageshow or the next visible minute check; an idle view is not a server lease.

This is not server-side JWT revocation: a copied token or independently issued bearer
credential remains usable until its existing expiry (or user deactivation). Clearing
one browser does not sign out a provider, other browsers or other devices. A failed
logout cannot promise cookie removal across closing/reopening the browser. Already
accepted server mutations cannot be undone by client disposal. Saved PostgreSQL data
survives logout; unsaved session drafts do not. No localStorage/sessionStorage credential
is written. The only sessionStorage value is a validated task-route destination across
an SSO redirect, removed after exchange.

## Navigation

Real pages: `/login`, `/register`, `/tasks`, `/tasks/mine`, `/tasks/overdue`,
`/projects/[id]`, retaining `/auth/callback` and public `/status`. `/` waits for bootstrap
and resolves to sign-in or `/tasks`. Anonymous protected links go to `/login?returnTo=…`;
only allowlisted task paths with validated query values can be returned to. Signed-in
visitors to anonymous pages are redirected without rendering the sign-in form.

Task URL state owns scope/project, status/due/priority, search, Attention signal, sort,
list/board and 50-row page offset. Project URLs may retain a combined scope in `scope`;
selecting a named scope in the sidebar leaves the project. Invalid/duplicate query
values fall back to defaults and unknown parameters are discarded. Search is bounded
to 200 non-control characters; offset is nonnegative, bounded to one million and rounded
down to a 50-row page. UUID project ids are required in HTTP mode; demo ids are accepted
only in explicit offline mode. Task selection and unsaved drafts are not URL state.

The reducer remains the workspace data/draft owner and the offline test seam. Routed
query actions compute a URL, not another independently authoritative query state. The
URL's projection is synchronized before rendering/querying, with no reducer-to-router
effect to undo Back/Forward. Next's documented native history integration preserves
the workspace while updating path/search hooks. Sidebar anchors have real destinations
and support open-in-new-tab; unmodified clicks use that integration. Filter/view/page
changes push history; search replaces the current entry and retains existing request
debouncing, so typing does not create a Back entry per keystroke.

## Evidence and limits

In-session project/priority filtering already worked at the task's base commit; the
failure was reload discarding memory auth and navigation state while PostgreSQL retained
records. Shared All tasks results are intentional, not an ownership leak. No tenant
isolation, deletion of retained records, dashboard, or invented task scope is added.

Tests cover cookie restoration, CSRF/origins, bearer precedence, SSO exchange, active
users, real PostgreSQL/JWT expiry, URL validation and round trips, query-driven browser
navigation, reload/new tab, Back/Forward, unsafe return targets, logout and temporary
bootstrap failures. Executable coverage lives in `tests/api/test_browser_session.py`,
`tests/integration/test_browser_session.py` (API), and `browserSession.test.ts`,
`route.test.ts`, `visual/http-session-routes.contract.ts` (web).
