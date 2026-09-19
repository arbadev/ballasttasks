"""The revision history itself, read from the scripts: no database needed."""

from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.postgres import API_ROOT

CREATE_USERS = "2dcaf48d517c"


def test_the_history_is_one_line_and_the_tasks_to_users_wiring_follows_create_users() -> None:
    scripts = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini")))

    heads = scripts.get_heads()
    assert len(heads) == 1
    head = scripts.get_revision(heads[0])
    assert head is not None
    assert head.down_revision == CREATE_USERS
    assert len(list(scripts.walk_revisions())) == 4
