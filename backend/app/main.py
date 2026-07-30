from fastapi import FastAPI

from app.alerts.router import router as alerts_router
from app.dashboard.router import router as dashboard_router
from app.evaluation.router import router as evaluation_router
from app.ingestion.router import router as ingestion_router
from app.remediation.router import router as remediation_router
from app.retest.router import router as retest_router


def create_app() -> FastAPI:
    app = FastAPI(title="AI Evaluation Iteration Workbench")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(ingestion_router)
    app.include_router(evaluation_router)
    app.include_router(alerts_router)
    app.include_router(remediation_router)
    app.include_router(retest_router)
    app.include_router(dashboard_router)

    return app


app = create_app()
