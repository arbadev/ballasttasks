"""The revision history itself, read from the scripts: no database needed."""

from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.postgres import API_ROOT

CREATE_USERS = "2dcaf48d517c"
WIRE_TASKS_TO_USERS = "fa7b13ec7508"
DESIGN_MODEL = "8b2f4c6d1a3e"


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


def test_user_identities_arrive_in_one_revision_after_the_tasks_to_users_wiring() -> None:
    scripts = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini")))

    oldest_first = list(reversed(list(scripts.walk_revisions())))
    (added,) = [revision for revision in oldest_first if revision.doc == "add user identities"]
    history = [revision.revision for revision in oldest_first]
    assert history.index(WIRE_TASKS_TO_USERS) < history.index(added.revision)
