"""Collaborators API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.collaborators.schemas import CollaboratorCreate, CollaboratorResponse, TenantSearchResult
from app.collaborators.service import CollaboratorService
from app.dependencies import CurrentAdmin, get_db

router = APIRouter()


def get_service(
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentAdmin,
) -> CollaboratorService:
    return CollaboratorService(db, str(current_user.tenant_id), str(current_user.id))


@router.get("", response_model=list[CollaboratorResponse])
async def list_collaborators(
    service: Annotated[CollaboratorService, Depends(get_service)],
):
    return service.list_collaborators()


@router.post("", response_model=CollaboratorResponse, status_code=status.HTTP_201_CREATED)
async def add_collaborator(
    data: CollaboratorCreate,
    service: Annotated[CollaboratorService, Depends(get_service)],
):
    try:
        return service.add_collaborator(data.collaborator_tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{collaborator_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_collaborator(
    collaborator_id: str,
    service: Annotated[CollaboratorService, Depends(get_service)],
):
    if not service.remove_collaborator(collaborator_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collaborator not found")


@router.get("/search-tenants", response_model=list[TenantSearchResult])
async def search_tenants(
    service: Annotated[CollaboratorService, Depends(get_service)],
    q: str = Query("", min_length=1),
    limit: int = Query(10, ge=1, le=50),
):
    return service.search_tenants(q, limit)
