import hmac
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
import strawberry
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi import Query as QueryParam
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from strawberry.fastapi import GraphQLRouter

from . import oltp
from .config import Settings, load_settings
from .olap import REPORTS, Analytics, RefreshInProgress, UnknownReport

STATIC = Path(__file__).parent / "static"


class OrderIn(BaseModel):
    customer_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=1000)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    analytics = Analytics(settings.duckdb_path, settings.pg_dsn, settings.max_rows)

    def require_key(x_api_key: str | None = Header(default=None)) -> None:
        if not x_api_key or not hmac.compare_digest(x_api_key.encode(), settings.api_key.encode()):
            raise HTTPException(401, "missing or invalid X-API-Key")

    def clamp(limit: int) -> int:
        return min(limit, settings.max_rows)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        analytics.close()

    app = FastAPI(title="Stonebreaker", version="0.1.0", lifespan=lifespan)
    app.state.analytics = analytics

    @app.exception_handler(oltp.OrderError)
    async def _order_err(_r, exc: oltp.OrderError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(psycopg.OperationalError)
    async def _pg_err(_r, exc):
        return JSONResponse({"detail": "transactional database unavailable"}, status_code=503)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    auth = [Depends(require_key)]

    @app.get("/api/products", dependencies=auth)
    def products(limit: int = QueryParam(50, ge=1)):
        return oltp.list_products(settings.pg_dsn, clamp(limit))

    @app.get("/api/orders", dependencies=auth)
    def orders(limit: int = QueryParam(20, ge=1)):
        return oltp.list_orders(settings.pg_dsn, clamp(limit))

    @app.post("/api/orders", status_code=201, dependencies=auth)
    def create_order(body: OrderIn):
        return oltp.place_order(settings.pg_dsn, body.customer_id, body.product_id, body.quantity)

    @app.get("/api/orders/{order_id}", dependencies=auth)
    def order(order_id: int):
        row = oltp.get_order(settings.pg_dsn, order_id)
        if row is None:
            raise HTTPException(404, "order not found")
        return row

    @app.post("/api/analytics/refresh", dependencies=auth)
    def refresh():
        try:
            return analytics.refresh()
        except RefreshInProgress as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/analytics/status", dependencies=auth)
    def status():
        return analytics.status()

    @app.get("/api/analytics/reports", dependencies=auth)
    def reports():
        return sorted(REPORTS)

    @app.get("/api/analytics/reports/{name}", dependencies=auth)
    def report(name: str, limit: int | None = QueryParam(None, ge=1)):
        try:
            return analytics.report(name, limit)
        except UnknownReport:
            raise HTTPException(404, "unknown report")
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    # ---- GraphQL (provisional interpretation of "graphsql") ----
    @strawberry.type
    class Product:
        id: int
        name: str
        category: str
        price_cents: int
        stock: int

    @strawberry.type
    class Order:
        id: int
        customer_id: int
        product_id: int
        quantity: int
        total_cents: int

    @strawberry.type
    class ReportRow:
        label: str
        revenue_cents: int
        count: int

    @strawberry.type
    class SyncStatus:
        status: str | None
        error: str | None
        last_success_at: str | None
        mode: str

    def _status() -> SyncStatus:
        s = analytics.status()
        last = s["last_run"] or {}
        return SyncStatus(status=last.get("status"), error=last.get("error"), last_success_at=s["last_success_at"], mode=s["mode"])

    @strawberry.type
    class Query:
        @strawberry.field
        def products(self, limit: int = 50) -> list[Product]:
            return [Product(**r) for r in oltp.list_products(settings.pg_dsn, max(1, clamp(limit)))]

        @strawberry.field
        def sync_status(self) -> SyncStatus:
            return _status()

        @strawberry.field
        def report(self, name: str, limit: int = 10) -> list[ReportRow]:
            rows = analytics.report(name, max(1, limit))
            return [
                ReportRow(
                    label=str(next(iter(r.values()))),
                    revenue_cents=int(r["revenue_cents"]),
                    count=int(r.get("orders") or r.get("units") or 0),
                )
                for r in rows
            ]

    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def place_order(self, customer_id: int, product_id: int, quantity: int) -> Order:
            return Order(**{k: v for k, v in oltp.place_order(settings.pg_dsn, customer_id, product_id, quantity).items() if k != "created_at"})

        @strawberry.mutation
        def refresh_analytics(self) -> SyncStatus:
            analytics.refresh()
            return _status()

    async def gql_context():
        return {}

    gql = GraphQLRouter(strawberry.Schema(query=Query, mutation=Mutation), context_getter=gql_context, graphql_ide=None)
    app.include_router(gql, prefix="/graphql", dependencies=auth)

    @app.get("/")
    def console():
        return FileResponse(STATIC / "index.html")

    return app
