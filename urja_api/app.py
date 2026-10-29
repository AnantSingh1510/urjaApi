from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .errors import ServiceError, protocol_error
from .models import Envelope, ErrorResponse, Meter, MeterPage, Readings
from .normalize import (
    meter_from_export,
    normalize_readings,
    summary_from_row,
    with_intervals,
)
from .portal import PortalClient


async def portal(request: Request):
    client = PortalClient(request.app.state.settings)
    try:
        yield client
    finally:
        await client.close()


Portal = Annotated[PortalClient, Depends(portal)]


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings or Settings()
        yield

    app = FastAPI(
        title="Urja Meter API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        description="Read-only access to Urja meter search, details, location, hierarchy and recent readings.",
        responses={
            code: {"model": ErrorResponse, "description": description}
            for code, description in {
                404: "Meter not found",
                502: "Unexpected portal response or authentication failure",
                503: "Portal unavailable",
                504: "Portal request timed out",
            }.items()
        },
    )

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {"code": exc.code, "message": exc.message},
            },
        )

    @app.get("/v1/meters", response_model=MeterPage)
    async def meters(
        client: Portal,
        q: Annotated[str, Query(max_length=100)] = "",
        page: Annotated[int, Query(ge=1)] = 1,
    ):
        """Search by meter ID or serial number using the portal's one-based pagination."""
        result = await client.search(q, page)
        if not isinstance(result.get("data"), list):
            raise protocol_error()
        for key in ("total", "page", "pageSize"):
            if type(result.get(key)) is not int:
                raise protocol_error()
        if (
            result["total"] < len(result["data"])
            or result["page"] != page
            or result["pageSize"] < 1
            or len(result["data"]) > result["pageSize"]
        ):
            raise protocol_error()
        return MeterPage(
            data=[summary_from_row(row) for row in result["data"]],
            total=result["total"],
            page=result["page"],
            page_size=result["pageSize"],
        )

    @app.get("/v1/meters/{meter_id}", response_model=Envelope[Meter])
    async def meter(meter_id: str, client: Portal):
        """Return nameplate fields, coordinates and the meter's reported network path."""
        return Envelope(data=meter_from_export(await client.meter(meter_id)))

    @app.get("/v1/meters/{meter_id}/readings", response_model=Readings)
    async def readings(meter_id: str, client: Portal):
        """Return the portal's default window. Timestamps assume the configured timezone.
        Registers are cumulative; interval kWh uses valid adjacent 30-minute differences.
        """
        data = with_intervals(
            normalize_readings(
                await client.readings(meter_id),
                client.settings.portal_timezone,
            )
        )
        timestamps = [row.timestamp for row in data if row.timestamp is not None]
        return Readings(
            meter_id=meter_id,
            timezone=client.settings.portal_timezone,
            available_from=min(timestamps) if timestamps else None,
            available_to=max(timestamps) if timestamps else None,
            data=data,
        )

    return app


app = create_app()
