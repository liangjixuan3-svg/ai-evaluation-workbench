from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="AI Evaluation Iteration Workbench")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
