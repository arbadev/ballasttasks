"""Explicit local entry point: ``python -m app.seed_demo``. Never called on startup."""

import asyncio
import sys
from collections.abc import Sequence

from app.application.clock import Clock, utc_now
from app.application.use_cases.seed_demo import DemoSeedConflictError
from app.bootstrap import build_container, load_settings

CONFIRM_FLAG = "--confirm-demo-accounts"

USAGE = (
    f"usage: python -m app.seed_demo {CONFIRM_FLAG}\n"
    f"{CONFIRM_FLAG} acknowledges that this database will hold demo accounts whose password "
    "is published in this repository. It records your intent only: nothing here can tell "
    "whether the configured database is a local one you own, so pass it only after checking "
    "DATABASE__URL yourself."
)


class DemoSeedRefusedError(ValueError):
    pass


async def run(*, confirmed: bool, clock: Clock = utc_now) -> bool:
    settings = load_settings()
    # Both checks precede constructing any adapter, opening a connection or starting a transaction.
    if settings.app.env == "production":
        raise DemoSeedRefusedError("Demo seed refused in production")
    if not confirmed:
        raise DemoSeedRefusedError(USAGE)
    container = build_container(settings, clock=clock)
    try:
        async with container.request_scope() as scope:
            return await scope.seed_demo.execute()
    finally:
        await container.aclose()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(argument != CONFIRM_FLAG for argument in arguments):
        print(USAGE, file=sys.stderr)  # noqa: T201
        return 1
    try:
        created = asyncio.run(run(confirmed=CONFIRM_FLAG in arguments))
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
