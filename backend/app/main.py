"""FastAPI app initialization and dataset lifecycle."""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app.api.routes.api import router
from app.core.config import DATA_DIR, FRONTEND_ORIGINS
from app.core.log_sanitizer import configure_sensitive_logging
from app.core.storage import SQLiteStore
from app.services.data_loader import load_dataset
from app.services.cache import CompanyResultCache

LOGGER = logging.getLogger(__name__)
FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Load static data and initialize local persistence once per process."""
    application.state.dataset = load_dataset(DATA_DIR)
    configure_sensitive_logging(application.state.dataset)
    application.state.data_directory = DATA_DIR
    application.state.default_data_directory = DATA_DIR
    application.state.dataset_storage_root = DATA_DIR.parent / ".managed-datasets"
    application.state.store = SQLiteStore()
    application.state.store.cleanup_events()
    dataset = application.state.dataset
    if not dataset.operations.empty:
        last_dates = dataset.operations.groupby("company_id")["date"].max()
        for company_id, last_actual_date in last_dates.items():
            application.state.store.ensure_diverse_events(
                str(company_id),
                last_actual_date.date(),
            )
    application.state.result_cache = CompanyResultCache(
        application.state.dataset.companies["company_id"].astype(str).tolist()
        if not application.state.dataset.companies.empty else []
    )
    LOGGER.info("%s", application.state.dataset.message)
    yield


app = FastAPI(
    title="Прогноз денежных потоков",
    description="Локальный API анализа выписок, прогноза ликвидности и управления событиями.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(router)

app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIST / "assets", check_dir=False),
    name="frontend-assets",
)


@app.get("/{full_path:path}", include_in_schema=False)
def frontend_app(full_path: str):
    """Serve built frontend files while leaving API and health paths to FastAPI."""
    normalized_path = full_path.strip("/")
    if normalized_path == "api" or normalized_path.startswith("api/") or normalized_path == "health":
        raise HTTPException(status_code=404, detail="Not found")

    requested_file = (FRONTEND_DIST / normalized_path).resolve()
    try:
        requested_file.relative_to(FRONTEND_DIST.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found") from None

    if normalized_path and requested_file.is_file():
        return FileResponse(requested_file)

    index_file = FRONTEND_DIST / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=404, detail="Frontend build is not available.")
    return FileResponse(index_file)
