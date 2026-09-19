import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.project import (
    DEFAULT_PROJECT_ID,
    DEFAULT_PROJECT_KEY,
    DEFAULT_PROJECT_NAME,
    PROJECT_NAME_MAX_LENGTH,
    InvalidProjectError,
    Project,
)
from app.domain.task_key import InvalidTaskKeyError, TaskKey

CREATED = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
LATER = CREATED + timedelta(hours=3)


def new_project(**overrides: object) -> Project:
    arguments: dict[str, object] = {
        "project_id": uuid.uuid4(),
        "name": "Ballast Tasks",
        "key": "BT",
        "now": CREATED,
    }
    return Project.create(**(arguments | overrides))  # type: ignore[arg-type]


def test_a_new_project_keeps_its_name_key_and_optional_colour() -> None:
    project_id = uuid.uuid4()

    project = Project.create(
        project_id=project_id, name="  Ballast Tasks ", key="BT", color="acc", now=CREATED
    )

    assert project.id == project_id
    assert project.name == "Ballast Tasks"
    assert project.key == "BT"
    assert project.color == "acc"
    assert project.created_at == CREATED
    assert project.updated_at == CREATED
    assert new_project().color is None


@pytest.mark.parametrize("key", ["BT", "INB", "ABCDE"])
def test_a_key_is_two_to_five_upper_case_letters(key: str) -> None:
    assert new_project(key=key).key == key


@pytest.mark.parametrize("key", ["", "B", "ABCDEF", "bt", "B1", "B-T", " BT", "ÑU", "BT\n"])
def test_any_other_key_is_rejected(key: str) -> None:
    with pytest.raises(InvalidProjectError):
        new_project(key=key)


@pytest.mark.parametrize("name", ["", "   ", "x" * (PROJECT_NAME_MAX_LENGTH + 1), "nul\x00"])
def test_a_blank_overlong_or_nul_name_is_rejected(name: str) -> None:
    with pytest.raises(InvalidProjectError):
        new_project(name=name)


@pytest.mark.parametrize("color", ["", "Acc", "var(--acc)", "a" * 33, "acc fg"])
def test_a_colour_is_a_short_lower_case_token(color: str) -> None:
    with pytest.raises(InvalidProjectError):
        new_project(color=color)


def test_renaming_and_recolouring_touch_updated_at_and_keep_the_key() -> None:
    project = new_project()

    project.rename("Ballast", now=LATER)
    project.recolor("fg-3", now=LATER)

    assert (project.name, project.color, project.key) == ("Ballast", "fg-3", "BT")
    assert project.updated_at == LATER
    assert project.created_at == CREATED


def test_a_rejected_rename_changes_nothing() -> None:
    project = new_project()

    with pytest.raises(InvalidProjectError):
        project.rename("  ", now=LATER)

    assert project.name == "Ballast Tasks"
    assert project.updated_at == CREATED


def test_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(InvalidProjectError):
        new_project(now=datetime(2026, 1, 5, 9, 0))


def test_the_default_project_is_the_inbox() -> None:
    assert uuid.UUID("00000000-0000-4000-8000-000000000001") == DEFAULT_PROJECT_ID
    assert (DEFAULT_PROJECT_NAME, DEFAULT_PROJECT_KEY) == ("Inbox", "IN")


# --- task keys -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prefix", "number", "text"),
    [("BT", 4, "BT-04"), ("BT", 12, "BT-12"), ("IN", 100, "IN-100"), ("ABCDE", 1, "ABCDE-01")],
)
def test_a_key_is_the_prefix_and_a_number_padded_to_two_digits(
    prefix: str, number: int, text: str
) -> None:
    assert str(TaskKey(prefix, number)) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [("BT-04", TaskKey("BT", 4)), ("bt-4", TaskKey("BT", 4)), ("In-0100", TaskKey("IN", 100))],
)
def test_parsing_accepts_any_case_and_any_padding(text: str, expected: TaskKey) -> None:
    assert TaskKey.parse(text) == expected


@pytest.mark.parametrize(
    "text", ["", "BT", "BT-", "-4", "BT-0", "BT--4", "B-4", "ABCDEF-4", "BT-4x", "BT 4", "BT-٤"]
)
def test_parsing_rejects_anything_else(text: str) -> None:
    with pytest.raises(InvalidTaskKeyError):
        TaskKey.parse(text)


def test_a_key_needs_a_valid_prefix_and_a_positive_number() -> None:
    for prefix, number in (("bt", 1), ("B", 1), ("BT", 0), ("BT", -1)):
        with pytest.raises(InvalidTaskKeyError):
            TaskKey(prefix, number)
