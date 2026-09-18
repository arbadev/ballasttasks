from app.infrastructure.ai.fake import FakeLanguageModel


async def test_generate_is_deterministic_and_echoes_the_prompt() -> None:
    model = FakeLanguageModel(model="fake-1")

    assert await model.generate("hello") == await model.generate("hello")
    assert "hello" in await model.generate("hello")


def test_describes_itself() -> None:
    model = FakeLanguageModel(model="fake-9")

    assert (model.provider, model.model) == ("fake", "fake-9")
