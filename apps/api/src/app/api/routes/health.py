from fastapi import APIRouter, Response, status

from app.api.dependencies import CheckReadinessDep, LanguageModelDep
from app.api.schemas.health import AiInfo, ComponentStatus, HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness: the API process is up")
async def health() -> HealthResponse:
    return HealthResponse()


@router.get(
    "/health/ready",
    summary="Readiness: every dependency is usable",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ReadinessResponse,
            "description": "At least one dependency failed its check",
        }
    },
)
async def ready(
    response: Response,
    check_readiness: CheckReadinessDep,
    language_model: LanguageModelDep,
) -> ReadinessResponse:
    report = await check_readiness.execute()
    if not report.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if report.ready else "not_ready",
        checks=[
            ComponentStatus(name=result.name, status="ok" if result.healthy else "failed")
            for result in report.results
        ],
        ai=AiInfo(provider=language_model.provider, model=language_model.model),
    )
