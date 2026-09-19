"""The attention rules, held to the design's own urgency function over a table of cases."""

import uuid
from datetime import date, timedelta

import pytest

from app.domain.attention import (
    SOON_WINDOW_DAYS,
    Attention,
    AttentionReason,
    assess,
    days_until,
    soon_window,
)
from app.domain.task import Task, TaskPriority, TaskStatus
from tests.urgency_cases import CASES, NOW, TODAY, UrgencyCase

CREATOR = uuid.uuid4()
PROJECT = uuid.uuid4()


def a_task(**overrides: object) -> Task:
    arguments: dict[str, object] = {
        "task_id": uuid.uuid4(),
        "title": "Write the report",
        "created_by": CREATOR,
        "project_id": PROJECT,
        "key": "BT-01",
        "assignee_id": CREATOR,
        "now": NOW,
    }
    return Task.create(**(arguments | overrides))  # type: ignore[arg-type]


def due_in(days: int) -> date:
    return TODAY + timedelta(days=days)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.label)
def test_attention_matches_the_design_urgency_function(case: UrgencyCase) -> None:
    attention = assess(case.task(created_by=CREATOR, project_id=PROJECT, number=1), today=TODAY)

    expected = case.expected
    assert attention.urgency == pytest.approx(expected.score)
    assert attention.is_overdue is expected.overdue
    assert attention.is_p0_at_risk is expected.critical
    # The design's "due soon" signal: not overdue, and due today or inside the window.
    assert attention.is_due_soon is (expected.today or expected.soon)
    assert attention.needs_owner is expected.unassigned
    assert attention.days_until_due == case.diff


def test_the_base_window_is_two_days_and_a_higher_priority_widens_it() -> None:
    assert SOON_WINDOW_DAYS == 2
    assert [soon_window(priority) for priority in TaskPriority] == [4, 3, 2, 2]


def test_days_until_counts_whole_calendar_days() -> None:
    assert days_until(due_in(3), today=TODAY) == 3
    assert days_until(due_in(-2), today=TODAY) == -2
    assert days_until(None, today=TODAY) is None


def test_a_calm_task_needs_no_attention() -> None:
    attention = assess(a_task(due_date=due_in(30)), today=TODAY)

    assert attention == Attention(
        is_overdue=False,
        is_due_soon=False,
        is_p0_at_risk=False,
        needs_owner=False,
        days_until_due=30,
        urgency=pytest.approx(50 + 5 + 3),
        reasons=(),
    )


def test_reasons_are_machine_readable_and_ordered_by_severity() -> None:
    overdue = assess(a_task(due_date=due_in(-1), assignee_id=None), today=TODAY)
    at_risk_today = assess(a_task(due_date=due_in(0), priority=TaskPriority.P0), today=TODAY)
    at_risk_soon = assess(a_task(due_date=due_in(4), priority=TaskPriority.P0), today=TODAY)
    soon = assess(a_task(due_date=due_in(2)), today=TODAY)

    assert overdue.reasons == (AttentionReason.OVERDUE, AttentionReason.NEEDS_OWNER)
    assert at_risk_today.reasons == (AttentionReason.P0_AT_RISK, AttentionReason.DUE_TODAY)
    assert at_risk_soon.reasons == (AttentionReason.P0_AT_RISK, AttentionReason.DUE_SOON)
    assert soon.reasons == (AttentionReason.DUE_SOON,)
    assert [reason.value for reason in AttentionReason] == [
        "overdue",
        "p0_at_risk",
        "due_today",
        "due_soon",
        "needs_owner",
    ]


def test_a_done_task_never_asks_for_attention() -> None:
    done = a_task(due_date=due_in(-10), assignee_id=None, priority=TaskPriority.P0)
    done.move_to(TaskStatus.DONE, now=NOW)

    attention = assess(done, today=TODAY)

    assert attention.reasons == ()
    assert attention.days_until_due == -10
    assert attention.urgency == pytest.approx(5 + 9)


def test_testing_counts_as_open() -> None:
    testing = a_task(due_date=due_in(-1), status=TaskStatus.TESTING)

    assert assess(testing, today=TODAY).is_overdue is True
