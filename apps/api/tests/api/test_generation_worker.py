from dataclasses import replace
from uuid import uuid4

from fastapi import FastAPI

from app.application.step_generation import GenerationOutcome
from app.bootstrap import generate_steps_in_worker
from tests.api.conftest import RecordingRequestScopes
from tests.builders import a_task
from tests.unit.test_generate_step_titles import Model


async def test_model_runs_outside_request_scope_and_never_writes(
    tasks_app: FastAPI, request_scopes: RecordingRequestScopes
) -> None:
    task = a_task(uuid4())
    # Repository fake enforces the same references as PostgreSQL.
    from tests.auth_fakes import a_user

    await request_scopes.auth.users.add(a_user(user_id=task.created_by))
    await request_scopes.tasks.add(task)

    class ScopeCheckingModel(Model):
        async def generate(self, prompt: str) -> str:
            assert request_scopes.events == ["begin", "commit"]
            assert not (await request_scopes.steps.list_for_task(task.id))
            return await super().generate(prompt)

    model = ScopeCheckingModel()
    container = replace(tasks_app.state.container, language_model=model)
    result = await generate_steps_in_worker(container, task.id)
    assert result == GenerationOutcome(("Plan", "Ship"))
    assert request_scopes.events == ["begin", "commit", "begin", "commit"]
    assert not (await request_scopes.steps.list_for_task(task.id))
    assert len(model.prompts) == 1


async def test_unknown_task_never_calls_provider(tasks_app: FastAPI) -> None:
    model = Model()
    result = await generate_steps_in_worker(
        replace(tasks_app.state.container, language_model=model), uuid4()
    )
    assert result.error == "task_deleted"
    assert not model.prompts


async def test_deletion_during_generation_discards_proposals(
    tasks_app: FastAPI, request_scopes: RecordingRequestScopes
) -> None:
    from tests.auth_fakes import a_user

    task = a_task(uuid4())
    await request_scopes.auth.users.add(a_user(user_id=task.created_by))
    await request_scopes.tasks.add(task)

    class DeletingModel(Model):
        async def generate(self, prompt: str) -> str:
            await request_scopes.tasks.delete(task.id)
            return self.response

    result = await generate_steps_in_worker(
        replace(tasks_app.state.container, language_model=DeletingModel()), task.id
    )
    assert result.error == "task_deleted"
    assert result.titles == ()


async def test_default_fake_provider_produces_offline_drafts() -> None:
    from app.application.use_cases.generate_step_titles import GenerateStepTitles
    from app.infrastructure.ai.fake import FakeLanguageModel

    result = await GenerateStepTitles(FakeLanguageModel(model="fake-1"), timeout_seconds=1).execute(
        title="An offline demo", description=None, existing_titles=[]
    )
    assert result.titles == ("Clarify the goal", "Implement the task", "Verify the result")
    assert result.error is None
