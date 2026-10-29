import hmac
import logging
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import APIKeyHeader
from pydantic import AwareDatetime
from starlette.exceptions import HTTPException

from .config import Settings
from .demo import DemoPortal
from .errors import ServiceError
from .models import (
    Envelope,
    ErrorResponse,
    Geo,
    Health,
    Meter,
    MeterResult,
    Network,
    Page,
    Readings,
    Summary,
    Transformer,
)
from .normalize import distance_km, with_intervals
from .portal import PortalClient
from .service import Service

logger = logging.getLogger("urja_api")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


def service(request: Request) -> Service:
    return request.app.state.service


async def authorize(request: Request, supplied: str | None = Security(api_key_header)):
    expected = request.app.state.settings.api_key.get_secret_value()
    if expected and (
        supplied is None or not hmac.compare_digest(supplied.encode(), expected.encode())
    ):
        raise ServiceError("unauthorized", "A valid X-API-Key is required.", 401)


def create_app(settings: Settings | None = None, portal=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings or Settings()
        upstream = portal or (DemoPortal() if config.demo else PortalClient(config))
        app.state.settings = config
        app.state.service = Service(upstream, config)
        try:
            yield
        finally:
            await upstream.close()

    app = FastAPI(
        title="Urja Meter API",
        version="1.0.0",
        lifespan=lifespan,
        description="Read-only adapter over Urja Meter Ops. Normalized meter inventory, network "
        "relationships, location search and cumulative energy readings. All data responses include "
        "fetch/expiry timestamps. `synthetic_demo` identifies offline demonstration data. "
        "X-API-Key is required only when URJA_API_KEY is configured.",
        responses={
            code: {"model": ErrorResponse, "description": description}
            for code, description in {
                401: "Invalid service API key",
                404: "Resource not found",
                422: "Invalid input",
                500: "Unexpected service error",
                502: "Invalid portal response or authentication failure",
                503: "Portal unavailable",
                504: "Portal deadline exceeded",
            }.items()
        },
    )

    @app.middleware("http")
    async def request_metadata(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def error_response(request: Request, status: int, code: str, message: str):
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": getattr(request.state, "request_id", "unknown"),
                }
            },
        )

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        return error_response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Exclude raw input/context which might contain secrets or untrusted bodies.
        fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        return error_response(request, 422, "invalid_input", "Invalid fields: " + ", ".join(fields))

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(request, exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.error(
            "Unhandled error request_id=%s type=%s", request.state.request_id, type(exc).__name__
        )
        response = error_response(request, 500, "internal_error", "An internal error occurred.")
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/docs")

    @app.get("/healthz", response_model=Health, tags=["Operations"])
    async def health():
        """Process liveness only. Does not authenticate to or check the portal."""
        return Health()

    router = APIRouter(prefix="/v1", dependencies=[Depends(authorize)])

    @router.get("/meters", response_model=Page[MeterResult], tags=["Meters"])
    async def meters(
        svc: Annotated[Service, Depends(service)],
        q: Annotated[str | None, Query(max_length=100)] = None,
        make: Annotated[str | None, Query(max_length=100)] = None,
        status: Annotated[str | None, Query(max_length=100)] = None,
        phase: Annotated[str | None, Query(max_length=30)] = None,
        transformer_code: Annotated[str | None, Query(max_length=100)] = None,
        latitude: Annotated[float | None, Query(ge=-90, le=90)] = None,
        longitude: Annotated[float | None, Query(ge=-180, le=180)] = None,
        radius_km: Annotated[float | None, Query(gt=0, le=20000)] = None,
        offset: Offset = 0,
        limit: Limit = 50,
    ):
        """Search the complete export. q matches ID/serial; other text filters are case-insensitive
        exact matches. Geographic search requires all three parameters and uses great-circle
        distance. Sort: distance then ID for geo search, otherwise ID. Offset is zero-based.
        """
        geo_inputs = (latitude, longitude, radius_km)
        if any(v is not None for v in geo_inputs) and not all(v is not None for v in geo_inputs):
            raise ServiceError(
                "invalid_input", "Provide latitude, longitude and radius_km together.", 422
            )
        center = Geo(latitude=latitude, longitude=longitude) if latitude is not None else None
        catalog = await svc.catalog()
        matches = []
        for meter in catalog.meters:
            if (
                q
                and q.casefold() not in meter.id.casefold()
                and q.casefold() not in (meter.serial_number or "").casefold()
            ):
                continue
            filters = (
                (make, meter.make),
                (status, meter.installation_status),
                (phase, meter.phase),
                (transformer_code, meter.transformer_code),
            )
            if any(
                value is not None and value.casefold() != (actual or "").casefold()
                for value, actual in filters
            ):
                continue
            distance = None
            if center:
                if meter.location is None:
                    continue
                distance = distance_km(center, meter.location)
                if distance > radius_km:
                    continue
            matches.append(
                MeterResult(
                    **meter.model_dump(),
                    distance_km=round(distance, 6) if distance is not None else None,
                )
            )
        if center:
            matches.sort(key=lambda m: (m.distance_km, m.id))
        return Page(
            data=matches[offset : offset + limit],
            total=len(matches),
            offset=offset,
            limit=limit,
            freshness=catalog.freshness,
        )

    @router.get("/meters/{meter_id}", response_model=Envelope[Meter], tags=["Meters"])
    async def meter(meter_id: str, svc: Annotated[Service, Depends(service)]):
        """Nameplate, coordinates, original hierarchy entries and data-quality issues."""
        data, freshness = await svc.meter(meter_id)
        return Envelope(data=data, freshness=freshness)

    @router.get("/meters/{meter_id}/readings", response_model=Readings, tags=["Readings"])
    async def readings(
        meter_id: str,
        svc: Annotated[Service, Depends(service)],
        start: Annotated[
            AwareDatetime | None, Query(description="Inclusive ISO 8601 timestamp with offset.")
        ] = None,
        end: Annotated[
            AwareDatetime | None, Query(description="Inclusive ISO 8601 timestamp with offset.")
        ] = None,
        offset: Offset = 0,
        limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    ):
        """Read the portal's default window. start/end filter that window locally; they do not
        fetch older history. Register values are cumulative. Interval deltas require unique,
        consecutive 30-minute timestamps and nondecreasing valid kWh. Summary covers the full
        filtered window before pagination. The first filtered reading has no interval delta.
        """
        if start is not None and end is not None and start > end:
            raise ServiceError("invalid_input", "start must be at or before end.", 422)
        entry = await svc.readings(meter_id)
        times = [r.timestamp for r in entry.data if r.timestamp is not None]
        filtered = [
            r
            for r in entry.data
            if (
                (start is None and end is None)
                or (
                    r.timestamp is not None
                    and (start is None or r.timestamp >= start)
                    and (end is None or r.timestamp <= end)
                )
            )
        ]
        normalized = with_intervals(filtered)
        deltas = [Decimal(str(r.interval_kwh)) for r in normalized if r.interval_kwh is not None]
        return Readings(
            meter_id=meter_id,
            timezone=svc.settings.portal_timezone,
            available_from=min(times) if times else None,
            available_to=max(times) if times else None,
            data=normalized[offset : offset + limit],
            total=len(normalized),
            offset=offset,
            limit=limit,
            valid_interval_kwh=float(sum(deltas, Decimal(0))),
            valid_intervals=len(deltas),
            excluded_intervals=max(0, len(normalized) - 1 - len(deltas)),
            freshness=entry.freshness,
            notes=[
                "Portal timestamps have no offset; "
                "the configured portal timezone is an assumption.",
                "Cumulative-register semantics are inferred from observed data, "
                "not a billing guarantee.",
                "Only the portal default window is fetched. "
                "Date filters do not extend its coverage.",
                "Invalid timestamps are retained without date filters "
                "and excluded when date filtering.",
            ],
        )

    @router.get("/transformers", response_model=Page[Transformer], tags=["Network"])
    async def transformers(
        svc: Annotated[Service, Depends(service)], offset: Offset = 0, limit: Limit = 50
    ):
        """Complete transformer directory fetched through all portal pages."""
        catalog = await svc.catalog()
        rows = sorted(catalog.transformers, key=lambda t: t.code)
        return Page(
            data=rows[offset : offset + limit],
            total=len(rows),
            offset=offset,
            limit=limit,
            freshness=catalog.freshness,
        )

    @router.get("/network", response_model=Network, tags=["Network"])
    async def network(svc: Annotated[Service, Depends(service)]):
        """Observed graph, not an invented tree. Node identity is level + code; unknown codes
        are parent-scoped. parent_ids are edges; names retains aliases.
        No relationships are repaired.
        """
        catalog = await svc.catalog()
        return Network(nodes=catalog.nodes, issues=catalog.issues, freshness=catalog.freshness)

    @router.get("/summary", response_model=Summary, tags=["Operations"])
    async def summary(svc: Annotated[Service, Depends(service)]):
        """Inventory counts and quality indicators. Checks readiness on a cold cache."""
        catalog = await svc.catalog()
        return Summary(
            meters=len(catalog.meters),
            transformers=len(catalog.transformers),
            meters_by_status=dict(
                sorted(Counter(m.installation_status or "unknown" for m in catalog.meters).items())
            ),
            meters_by_make=dict(
                sorted(Counter(m.make or "unknown" for m in catalog.meters).items())
            ),
            meters_with_issues=sum(bool(m.issues) for m in catalog.meters),
            network_issues=len(catalog.issues),
            freshness=catalog.freshness,
        )

    app.include_router(router)
    return app


app = create_app()
