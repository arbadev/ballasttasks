from app.application.clock import Clock, today_utc, utc_now
from app.domain.attention import Attention, assess
from app.domain.task import Task


class AssessAttention:
    """What about a task asks for attention today. The rules are the domain's
    (``app.domain.attention``); this only supplies the day, from an injectable clock."""

    def __init__(self, *, clock: Clock = utc_now) -> None:
        self._clock = clock

    def execute(self, task: Task) -> Attention:
        return assess(task, today=today_utc(self._clock))
