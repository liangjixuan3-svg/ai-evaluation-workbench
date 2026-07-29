from fastapi import FastAPI

from app.evaluation.router import router as evaluation_router
from app.ingestion.router import router as ingestion_router


def create_app() -> FastAPI:
    app = FastAPI(title="AI Evaluation Iteration Workbench")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(ingestion_router)
    app.include_router(evaluation_router)

    return app


app = create_app()
