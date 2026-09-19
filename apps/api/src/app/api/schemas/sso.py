from pydantic import BaseModel, ConfigDict, Field

from app.application.sso import MAX_SECRET_LENGTH


class SsoProvider(BaseModel):
    """An enabled identity provider. ``name`` is the path segment of its start URL."""

    name: str = Field(examples=["google"])


class SsoProvidersResponse(BaseModel):
    """What the login screen offers. An envelope, so a provider can gain fields (a label, an
    icon) and the list can gain siblings without breaking clients. Empty when single
    sign-on is disabled."""

    providers: list[SsoProvider]


class SsoExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        min_length=1,
        max_length=MAX_SECRET_LENGTH,
        description="The one-time code the web app's callback URL received. Works once.",
        json_schema_extra={"writeOnly": True},
    )
