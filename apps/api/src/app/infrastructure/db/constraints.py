"""Which named constraint a rejected statement broke.

Every constraint has a stable name (``Base.metadata``'s naming convention), so a repository
can turn the one violation it expects into an application error and re-raise the rest.
"""

from sqlalchemy.exc import IntegrityError


def violated_constraint(error: IntegrityError) -> str | None:
    diagnostics = getattr(error.orig, "diag", None)
    name = getattr(diagnostics, "constraint_name", None)
    return name if isinstance(name, str) else None
