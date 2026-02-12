"""Crosses API routes."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.crosses.schemas import (
    CrossComplete,
    CrossCreate,
    CrossListResponse,
    CrossResponse,
    CrossSearchParams,
    CrossUpdate,
    SuggestGenotypesRequest,
    SuggestGenotypesResponse,
)
from app.crosses.service import CrossService, get_cross_service
from app.db.models import CrossStatus
from app.dependencies import CurrentTenantId, CurrentUser, get_db

logger = logging.getLogger(__name__)

router = APIRouter()


def get_service(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> CrossService:
    """Get cross service dependency."""
    return get_cross_service(db, str(tenant_id))


@router.post("/suggest-genotypes", response_model=SuggestGenotypesResponse)
async def suggest_genotypes(
    data: SuggestGenotypesRequest,
    current_user: CurrentUser,
):
    """Suggest F1 offspring genotypes using LLM analysis.

    Sends parent stock info (genotype, original_genotype, shortname, notes)
    to a reasoning LLM to predict likely offspring genotypes.

    Args:
        data: Request with female and male parent stock info.
        current_user: Current authenticated user.

    Returns:
        SuggestGenotypesResponse: Suggested genotypes and chromosome reasoning.

    Raises:
        HTTPException: If LLM is not configured or request fails.
    """
    from app.config import get_settings
    from app.llm.service import get_llm_service

    llm = get_llm_service()
    if not llm.configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AI features are not configured. Set LLM_API_KEY in your environment.",
        )

    settings = get_settings()
    # Use reasoning model for complex genetics if configured, else default
    model = settings.llm_reasoning_model or settings.llm_default_model

    # Build rich context for each parent
    def format_parent(parent, sex: str) -> str:
        lines = [f"{sex} parent genotype: {parent.genotype}"]
        if parent.original_genotype:
            lines.append(f"  Original/FlyBase genotype: {parent.original_genotype}")
        if parent.shortname:
            lines.append(f"  Shortname: {parent.shortname}")
        if parent.notes:
            lines.append(f"  Notes: {parent.notes}")
        if parent.chromosome_info:
            lines.append(f"  User-provided chromosome info: {parent.chromosome_info}")
        return "\n".join(lines)

    female_info = format_parent(data.female, "Female (virgin)")
    male_info = format_parent(data.male, "Male")

    prompt = f"""You are a Drosophila genetics expert. Given two parent stocks, predict the most useful F1 offspring genotypes.

{female_info}

{male_info}

Instructions:
1. First, analyze each component in both genotypes and identify which chromosome each is on. Use your knowledge of Drosophila genetics (e.g., CyO is a chr 2 balancer, TM3/TM6B are chr 3 balancers, attP2 is on chr 3L, attP40 is on chr 2, X-linked markers like w, y, f, etc.).
2. Then predict 3-5 of the most useful/common F1 offspring genotypes researchers would want.
3. Use standard Drosophila notation.

Return your response in this exact format:
REASONING:
[Your chromosome analysis here - be concise]

GENOTYPES:
[genotype 1]
[genotype 2]
[genotype 3]
..."""

    try:
        response = await llm.ask(
            prompt=prompt,
            model=model,
            temperature=0.3,
            max_tokens=1024,
        )

        # Parse the structured response
        reasoning = None
        suggestions = []

        if "REASONING:" in response and "GENOTYPES:" in response:
            parts = response.split("GENOTYPES:")
            reasoning_part = parts[0].replace("REASONING:", "").strip()
            genotypes_part = parts[1].strip()
            reasoning = reasoning_part
            suggestions = [
                line.strip()
                for line in genotypes_part.split("\n")
                if line.strip() and not line.strip().startswith("#")
            ]
        else:
            # Fallback: treat each line as a genotype
            suggestions = [
                line.strip()
                for line in response.split("\n")
                if line.strip() and not line.strip().startswith("#")
            ]

        # Limit to 5 suggestions
        suggestions = suggestions[:5]

        return SuggestGenotypesResponse(
            suggestions=suggestions,
            reasoning=reasoning,
        )

    except ValueError as e:
        logger.error(f"LLM error suggesting genotypes: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate genotype suggestions",
        )


@router.get("", response_model=CrossListResponse)
async def list_crosses(
    service: Annotated[CrossService, Depends(get_service)],
    query: str | None = Query(None, description="Search query"),
    status: CrossStatus | None = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List crosses with filtering and pagination.

    Args:
        service: Cross service.
        query: Search query.
        status: Filter by status.
        page: Page number.
        page_size: Items per page.

    Returns:
        CrossListResponse: Paginated cross list.
    """
    params = CrossSearchParams(
        query=query,
        status=status,
        page=page,
        page_size=page_size,
    )
    return service.list_crosses(params)


@router.post("", response_model=CrossResponse, status_code=status.HTTP_201_CREATED)
async def create_cross(
    data: CrossCreate,
    service: Annotated[CrossService, Depends(get_service)],
    current_user: CurrentUser,
):
    """Create a new cross (plan).

    Args:
        data: Cross creation data.
        service: Cross service.
        current_user: Current user.

    Returns:
        CrossResponse: Created cross.

    Raises:
        HTTPException: If creation fails.
    """
    try:
        cross = service.create_cross(data, current_user.id)
        return service._cross_to_response(cross)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/{cross_id}", response_model=CrossResponse)
async def get_cross(
    cross_id: str,
    service: Annotated[CrossService, Depends(get_service)],
):
    """Get a cross by ID.

    Args:
        cross_id: Cross UUID.
        service: Cross service.

    Returns:
        CrossResponse: Cross details.

    Raises:
        HTTPException: If cross not found.
    """
    cross = service.get_cross(cross_id)
    if not cross:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cross not found",
        )
    return service._cross_to_response(cross)


@router.put("/{cross_id}", response_model=CrossResponse)
async def update_cross(
    cross_id: str,
    data: CrossUpdate,
    service: Annotated[CrossService, Depends(get_service)],
):
    """Update a cross.

    Args:
        cross_id: Cross UUID.
        data: Update data.
        service: Cross service.

    Returns:
        CrossResponse: Updated cross.

    Raises:
        HTTPException: If cross not found.
    """
    cross = service.update_cross(cross_id, data)
    if not cross:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cross not found",
        )
    return service._cross_to_response(cross)


@router.post("/{cross_id}/start", response_model=CrossResponse)
async def start_cross(
    cross_id: str,
    service: Annotated[CrossService, Depends(get_service)],
):
    """Mark a cross as in progress.

    Args:
        cross_id: Cross UUID.
        service: Cross service.

    Returns:
        CrossResponse: Updated cross.

    Raises:
        HTTPException: If cross not found.
    """
    cross = service.start_cross(cross_id)
    if not cross:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cross not found",
        )
    return service._cross_to_response(cross)


@router.post("/{cross_id}/complete", response_model=CrossResponse)
async def complete_cross(
    cross_id: str,
    data: CrossComplete,
    service: Annotated[CrossService, Depends(get_service)],
):
    """Mark a cross as completed.

    Args:
        cross_id: Cross UUID.
        data: Completion data.
        service: Cross service.

    Returns:
        CrossResponse: Updated cross.

    Raises:
        HTTPException: If cross not found.
    """
    cross = service.complete_cross(cross_id, data)
    if not cross:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cross not found",
        )
    return service._cross_to_response(cross)


@router.post("/{cross_id}/fail", response_model=CrossResponse)
async def fail_cross(
    cross_id: str,
    service: Annotated[CrossService, Depends(get_service)],
    notes: str | None = None,
):
    """Mark a cross as failed.

    Args:
        cross_id: Cross UUID.
        service: Cross service.
        notes: Optional failure notes.

    Returns:
        CrossResponse: Updated cross.

    Raises:
        HTTPException: If cross not found.
    """
    cross = service.fail_cross(cross_id, notes)
    if not cross:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cross not found",
        )
    return service._cross_to_response(cross)


@router.delete("/{cross_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cross(
    cross_id: str,
    service: Annotated[CrossService, Depends(get_service)],
):
    """Delete a cross.

    Args:
        cross_id: Cross UUID.
        service: Cross service.

    Raises:
        HTTPException: If cross not found.
    """
    if not service.delete_cross(cross_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cross not found",
        )


@router.post("/send-reminders")
async def send_cross_reminders(
    x_cron_secret: Annotated[str | None, Header()] = None,
):
    """Trigger cross timeline reminder emails (for cron jobs).

    Sends reminders about crosses needing vial flips or virgin collection.

    Args:
        x_cron_secret: Secret key for authentication.

    Returns:
        dict: Summary of emails sent.

    Raises:
        HTTPException: If secret key is invalid.
    """
    from app.config import get_settings

    settings = get_settings()

    expected_secret = getattr(settings, "cron_secret_key", None)
    if expected_secret and x_cron_secret != expected_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid cron secret",
        )

    # Late import to avoid circular imports
    from app.scheduler.cross_reminders import send_all_cross_reminders

    result = send_all_cross_reminders()
    return result
