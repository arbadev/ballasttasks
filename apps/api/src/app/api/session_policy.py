"""HTTP-only session policy, supplied by the composition root, not environment readers."""

from dataclasses import dataclass

from fastapi import HTTPException, Request, Response

SESSION_COOKIE = "bt_session"


@dataclass(frozen=True)
class BrowserSessionPolicy:
    origins: tuple[str, ...]
    secure: bool
    lifetime_seconds: int

    def protect(self, request: Request) -> None:
        # A non-simple header forces a CORS preflight. Check Origin ourselves as well:
        # CORS alone only protects reads, not simple cross-origin writes/login CSRF.
        if (
            request.headers.get("origin") not in self.origins
            or request.headers.get("x-csrf-protection") != "1"
        ):
            raise HTTPException(403, "Browser request origin or CSRF protection was not accepted")

    def issue(self, response: Response, token: str) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=self.lifetime_seconds,
            httponly=True,
            secure=self.secure,
            samesite="lax",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"

    def clear(self, response: Response) -> None:
        response.delete_cookie(
            SESSION_COOKIE, httponly=True, secure=self.secure, samesite="lax", path="/"
        )
        response.headers["Cache-Control"] = "no-store"
