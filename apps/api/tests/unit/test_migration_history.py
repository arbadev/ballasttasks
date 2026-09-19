"""The revision history itself, read from the scripts: no database needed."""

from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.postgres import API_ROOT

CREATE_USERS = "2dcaf48d517c"
WIRE_TASKS_TO_USERS = "fa7b13ec7508"
DESIGN_MODEL = "8b2f4c6d1a3e"
ATTACHMENTS = "c4a9e7d21b65"


def test_the_history_is_one_line_and_each_revision_follows_what_it_builds_on() -> None:
    scripts = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini")))

    assert len(scripts.get_heads()) == 1
    assert len(scripts.get_bases()) == 1
    oldest_first = list(reversed(list(scripts.walk_revisions())))
    assert all(not revision.is_branch_point for revision in oldest_first)
    assert all(not revision.is_merge_point for revision in oldest_first)
    history = [revision.revision for revision in oldest_first]
    assert history.index(CREATE_USERS) < history.index(WIRE_TASKS_TO_USERS)
    assert history.index(WIRE_TASKS_TO_USERS) < history.index(DESIGN_MODEL)
    assert history.index(DESIGN_MODEL) < history.index(ATTACHMENTS)
