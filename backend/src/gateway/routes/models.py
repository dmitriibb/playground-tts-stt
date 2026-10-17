"""Model management for both modules. Model ids are routed to the owning module."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends

from common.schemas import LoadRequest, ModelInfo, RunnerConfigPatch
from gateway.deps import service_for_model, services

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=list[ModelInfo])
async def list_models(task: Literal["stt", "tts"] | None = None, svc=Depends(services)) -> list[ModelInfo]:
    models: list[ModelInfo] = []
    if task in (None, "stt"):
        models += svc.stt.list_models()
    if task in (None, "tts"):
        models += svc.tts.list_models()
    return models


@router.get("/{model_id}", response_model=ModelInfo)
async def get_model(model_id: str, svc=Depends(services)) -> ModelInfo:
    return service_for_model(svc, model_id).model(model_id)


@router.post("/{model_id}/download", response_model=ModelInfo, status_code=202)
async def download(model_id: str, svc=Depends(services)) -> ModelInfo:
    return service_for_model(svc, model_id).start_download(model_id)


@router.delete("/{model_id}/files", response_model=ModelInfo)
async def delete_files(model_id: str, svc=Depends(services)) -> ModelInfo:
    return await service_for_model(svc, model_id).delete_files(model_id)


@router.post("/{model_id}/load", response_model=ModelInfo)
async def load(model_id: str, req: LoadRequest, svc=Depends(services)) -> ModelInfo:
    return await service_for_model(svc, model_id).load(model_id, req)


@router.post("/{model_id}/unload", response_model=ModelInfo)
async def unload(model_id: str, svc=Depends(services)) -> ModelInfo:
    return await service_for_model(svc, model_id).unload(model_id)


@router.patch("/{model_id}/runner", response_model=ModelInfo)
async def patch_runner(model_id: str, patch: RunnerConfigPatch, svc=Depends(services)) -> ModelInfo:
    """All runner settings apply live; changing max_active restarts the model's workers
    after their current job."""
    return service_for_model(svc, model_id).patch_runner(model_id, patch)
