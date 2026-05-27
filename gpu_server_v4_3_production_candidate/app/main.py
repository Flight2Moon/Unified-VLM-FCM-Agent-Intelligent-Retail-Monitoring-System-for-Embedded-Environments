from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import Settings, ensure_storage_dirs
from app.core.db import Database
from app.core.logging import setup_logging
from app.routers import dashboard, dataset, detection_policy, edge_nodes, events, models, storage, training
from app.services.dataset_builder import DatasetBuilder
from app.services.edge_node_service import EdgeNodeService
from app.services.event_ingestion import EventIngestionService
from app.services.event_processor import EventProcessor
from app.services.graph_memory import GraphMemory
from app.services.label_stats_service import LabelStatsService
from app.services.model_registry import ModelRegistry
from app.services.policy_service import PolicyService
from app.services.retention import RetentionService
from app.services.scoring import AnomalyScorer
from app.services.training_service import TrainingService
from app.services.vlm_client import OllamaClient
from app.services.vlm_relation.relation_extractor import VLMRelationExtractor
from app.services.websocket_manager import WebSocketManager


def create_app() -> FastAPI:
    settings = Settings()
    ensure_storage_dirs(settings)
    logger = setup_logging(settings.get("storage.logs_dir", "./storage/logs"))
    app = FastAPI(title=settings.get("server.title", "EAGER GPU Server v4"))
    app.state.settings = settings
    app.state.logger = logger

    if settings.get("api.enable_cors", True):
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.get("api.cors_origins", ["*"]),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    db = Database(settings.get("storage.db_path", "./storage/eager_server.sqlite3"))
    app.state.db = db
    app.state.ws_manager = WebSocketManager()
    app.state.ingestion = EventIngestionService(
        db,
        events_dir=settings.get("storage.events_dir", "./storage/events"),
        max_upload_mb=int(settings.get("server.max_upload_mb", 120)),
        keep_zip=bool(settings.get("processing.keep_uploaded_zip", True)),
    )
    app.state.policy_service = PolicyService(db, settings.section("detection_policy"), settings.get("storage.root_dir", "./storage"))
    app.state.label_stats = LabelStatsService(db)
    app.state.dataset_builder = DatasetBuilder(db, settings.section("dataset_builder"))
    profile = settings.get("runtime.profile", os.environ.get("EAGER_RUNTIME_PROFILE", "low_vram"))
    app.state.ollama = OllamaClient(
        settings.section("ollama"),
        runtime_profile=profile,
        gemini_cfg=settings.section("gemini"),
        provider=settings.get("vlm.provider"),
    )
    relation_cfg = settings.section("vlm_relation")
    # pass important labels to selector
    relation_cfg.setdefault("important_labels", settings.get("detection_policy.important_labels", []))
    app.state.relation_extractor = VLMRelationExtractor(relation_cfg, app.state.ollama, settings.section("relation_geometry"))
    store_near = bool(settings.get("vlm_relation.consolidation.store_near_in_memory", False))
    app.state.graph_memory = GraphMemory(db, store_near=store_near)
    app.state.scorer = AnomalyScorer(settings.section("scoring"))
    app.state.event_processor = EventProcessor(
        db,
        app.state.relation_extractor,
        app.state.label_stats,
        app.state.dataset_builder,
        app.state.graph_memory,
        app.state.scorer,
        settings.get("processing.keyframe_names", {}),
    )
    app.state.edge_nodes = EdgeNodeService(db)
    app.state.training = TrainingService(settings.section("training"))
    app.state.model_registry = ModelRegistry(db, settings.get("storage.models_dir", "./storage/model_registry"))
    app.state.retention = RetentionService(settings.section("retention"), settings.get("storage.root_dir", "./storage"))

    app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")
    app.include_router(events.router)
    app.include_router(detection_policy.router)
    app.include_router(dataset.router)
    app.include_router(edge_nodes.router)
    app.include_router(training.router)
    app.include_router(models.router)
    app.include_router(storage.router)
    app.include_router(dashboard.router)


    @app.on_event("startup")
    def recover_stale_events_on_startup():
        try:
            recovered = app.state.ingestion.recover_stale_events(
                older_than_sec=int(settings.get("processing.recovery.older_than_sec", 600)),
                action=settings.get("processing.recovery.startup_action", "mark_failed"),
            )
            if recovered:
                logger.warning("Recovered stale events on startup: %s", recovered)
        except Exception:
            logger.exception("startup stale event recovery failed")

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "eager_gpu_server_v4",
            "runtime_profile": profile,
            "ollama": app.state.ollama.health(),
            "vlm_provider": app.state.ollama.provider_name,
            "model": app.state.ollama.model,
        }

    @app.get("/api/runtime")
    def runtime():
        return {
            "profile": profile,
            "config_path": settings.config_path,
            "ollama_model": app.state.ollama.model,
            "storage": app.state.retention.stats(),
        }

    return app


app = create_app()
