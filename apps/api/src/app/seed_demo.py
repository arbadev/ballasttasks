"""Explicit local entry point: ``python -m app.seed_demo``. Never called on startup."""

import asyncio
import sys

from app.application.clock import Clock, utc_now
from app.application.use_cases.seed_demo import DemoSeedConflictError
from app.bootstrap import build_container, load_settings


class DemoSeedRefusedError(ValueError):
    pass


async def run(*, clock: Clock = utc_now) -> bool:
    settings = load_settings()
    # Check before constructing any adapter, opening a connection or starting a transaction.
    if settings.app.env == "production":
        raise DemoSeedRefusedError("Demo seed refused in production")
    container = build_container(settings, clock=clock)
    try:
        async with container.request_scope() as scope:
            return await scope.seed_demo.execute()
    finally:
        await container.aclose()


def main() -> int:
    try:
        created = asyncio.run(run())
    except (DemoSeedRefusedError, DemoSeedConflictError) as error:
        print(str(error), file=sys.stderr)  # noqa: T201
        return 1
    except Exception:
        # Driver/config errors can contain secrets. No tracebacks or connection URLs here.
        print(  # noqa: T201
            "Demo seed failed; no demo changes committed. Check configuration and migrations.",
            file=sys.stderr,
        )
        return 1
    print("Demo created" if created else "Demo unchanged")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
