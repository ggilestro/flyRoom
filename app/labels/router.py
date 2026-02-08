"""Labels API routes."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.db.models import PrintJobStatus
from app.dependencies import CurrentTenantId, CurrentUserId, get_db
from app.labels.print_service import PrintService, get_print_service
from app.labels.schemas import (
    AgentPairRequest,
    AgentPairResponse,
    PairingSessionResponse,
    PrintAgentConfigResponse,
    PrintAgentCreate,
    PrintAgentHeartbeat,
    PrintAgentHeartbeatResponse,
    PrintAgentResponse,
    PrintAgentUpdate,
    PrintAgentWithKey,
    PrintJobComplete,
    PrintJobCreate,
    PrintJobLabels,
    PrintJobResponse,
)
from app.labels.service import LabelService, get_label_service

router = APIRouter()


def get_service(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> LabelService:
    """Get label service dependency."""
    return get_label_service(db, str(tenant_id))


def get_print_svc(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
    user_id: CurrentUserId,
) -> PrintService:
    """Get print service dependency."""
    return get_print_service(db, str(tenant_id), str(user_id) if user_id else None)


async def get_agent_from_api_key(
    db: Annotated[Session, Depends(get_db)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> tuple[PrintService, str]:
    """Authenticate agent by API key header.

    Returns:
        tuple[PrintService, str]: Print service and agent ID.

    Raises:
        HTTPException: If API key invalid.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    # Create a service without tenant restriction for API key lookup
    svc = PrintService(db, tenant_id="")
    agent = svc.get_agent_by_api_key(x_api_key)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # Update heartbeat
    svc.update_agent_heartbeat(agent.id)

    # Return service scoped to agent's tenant
    return get_print_service(db, agent.tenant_id), agent.id


@router.get("/formats")
async def list_formats(
    service: Annotated[LabelService, Depends(get_service)],
):
    """List available label formats.

    Args:
        service: Label service.

    Returns:
        list[dict]: Available label formats.
    """
    return service.get_formats()


@router.get("/stock/{stock_id}/qr")
async def get_stock_qr(
    stock_id: str,
    service: Annotated[LabelService, Depends(get_service)],
    size: int = Query(200, ge=50, le=500),
):
    """Get QR code for a stock.

    Args:
        stock_id: Stock UUID.
        service: Label service.
        size: QR code size in pixels.

    Returns:
        Response: PNG image.

    Raises:
        HTTPException: If stock not found.
    """
    qr_data = service.generate_qr(stock_id, size=size)
    if not qr_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock not found",
        )

    return Response(
        content=qr_data,
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename=qr_{stock_id}.png"},
    )


@router.get("/stock/{stock_id}/barcode")
async def get_stock_barcode(
    stock_id: str,
    service: Annotated[LabelService, Depends(get_service)],
):
    """Get barcode for a stock.

    Args:
        stock_id: Stock UUID.
        service: Label service.

    Returns:
        Response: PNG image.

    Raises:
        HTTPException: If stock not found.
    """
    barcode_data = service.generate_barcode(stock_id)
    if not barcode_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock not found",
        )

    return Response(
        content=barcode_data,
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename=barcode_{stock_id}.png"},
    )


@router.get("/stock/{stock_id}/label")
async def get_stock_label(
    stock_id: str,
    service: Annotated[LabelService, Depends(get_service)],
    format: str = Query("brother_29mm", description="Label format"),
    include_qr: bool = Query(True),
    include_barcode: bool = Query(True),
):
    """Get full label data for a stock.

    Args:
        stock_id: Stock UUID.
        service: Label service.
        format: Label format name.
        include_qr: Whether to include QR code.
        include_barcode: Whether to include barcode.

    Returns:
        dict: Label data with base64-encoded images.

    Raises:
        HTTPException: If stock not found or invalid format.
    """
    try:
        label_data = service.generate_label_data(
            stock_id,
            format_name=format,
            include_qr=include_qr,
            include_barcode=include_barcode,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if not label_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock not found",
        )

    return label_data


@router.post("/batch")
async def generate_batch_labels(
    stock_ids: list[str],
    service: Annotated[LabelService, Depends(get_service)],
    format: str = Query("brother_29mm", description="Label format"),
):
    """Generate labels for multiple stocks.

    Args:
        stock_ids: List of stock UUIDs.
        service: Label service.
        format: Label format name.

    Returns:
        list[dict]: List of label data.
    """
    try:
        return service.generate_batch_labels(stock_ids, format_name=format)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/stock/{stock_id}/pdf")
async def get_stock_pdf(
    stock_id: str,
    service: Annotated[LabelService, Depends(get_service)],
    format: str = Query("dymo_11352", description="Label format"),
    code_type: str = Query("qr", description="Code type: 'qr' or 'barcode'"),
):
    """Get PDF label for a stock.

    Generates a properly sized PDF for direct thermal printing.

    Args:
        stock_id: Stock UUID.
        service: Label service.
        format: Label format name.
        code_type: Type of code to render ("qr" or "barcode").

    Returns:
        Response: PDF file.

    Raises:
        HTTPException: If stock not found or invalid format.
    """
    if code_type not in ("qr", "barcode"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="code_type must be 'qr' or 'barcode'",
        )

    try:
        pdf_data = service.generate_pdf(stock_id, label_format=format, code_type=code_type)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if not pdf_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock not found",
        )

    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=label_{stock_id}.pdf",
        },
    )


@router.post("/batch/pdf")
async def generate_batch_pdf(
    stock_ids: list[str],
    service: Annotated[LabelService, Depends(get_service)],
    format: str = Query("dymo_11352", description="Label format"),
    code_type: str = Query("qr", description="Code type: 'qr' or 'barcode'"),
):
    """Generate a multi-page PDF with labels for multiple stocks.

    Each label is on its own page, suitable for thermal printers.

    Args:
        stock_ids: List of stock UUIDs.
        service: Label service.
        format: Label format name.
        code_type: Type of code to render ("qr" or "barcode").

    Returns:
        Response: PDF file with all labels.

    Raises:
        HTTPException: If no stocks found or invalid format.
    """
    if not stock_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No stock IDs provided",
        )

    if code_type not in ("qr", "barcode"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="code_type must be 'qr' or 'barcode'",
        )

    try:
        pdf_data = service.generate_batch_pdf(stock_ids, label_format=format, code_type=code_type)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if not pdf_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No stocks found",
        )

    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=labels_batch.pdf",
        },
    )


@router.get("/pdf-formats")
async def list_pdf_formats(
    service: Annotated[LabelService, Depends(get_service)],
):
    """List available PDF label formats.

    Args:
        service: Label service.

    Returns:
        list[dict]: Available PDF label formats with dimensions.
    """
    return service.get_pdf_formats()


@router.get("/test-label/pdf")
async def get_test_label_pdf(
    service: Annotated[LabelService, Depends(get_service)],
    format: str = Query("dymo_11352", description="Label format"),
):
    """Generate a test label PDF to verify printer alignment.

    The test label contains a border rectangle and crosshairs
    to help verify that labels are properly centered.

    Args:
        service: Label service.
        format: Label format key.

    Returns:
        Response: PDF file.
    """
    from app.labels.pdf_generator import create_test_label_pdf

    pdf_data = create_test_label_pdf(label_format=format)
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=test_label.pdf"},
    )


@router.post("/test-label/print")
async def print_test_label(
    svc: Annotated[PrintService, Depends(get_print_svc)],
    format: str = Query("dymo_11352", description="Label format"),
):
    """Create a print job for a test label.

    Args:
        svc: Print service.
        format: Label format key.

    Returns:
        dict: Print job info.
    """

    # Create a special test job
    job = svc.create_test_job(label_format=format)
    return {"message": "Test label job created", "job_id": str(job.id)}


# ============================================================================
# Print Agent Endpoints (Admin/User facing)
# ============================================================================


@router.post("/agents", response_model=PrintAgentWithKey)
async def create_print_agent(
    data: PrintAgentCreate,
    svc: Annotated[PrintService, Depends(get_print_svc)],
):
    """Create a new print agent.

    Returns the agent with its API key (only shown once).

    Args:
        data: Agent creation data.
        svc: Print service.

    Returns:
        PrintAgentWithKey: Created agent with API key.
    """
    agent, api_key = svc.create_agent(data)
    return PrintAgentWithKey(
        id=agent.id,
        tenant_id=agent.tenant_id,
        name=agent.name,
        printer_name=agent.printer_name,
        label_format=agent.label_format,
        last_seen=agent.last_seen,
        is_active=agent.is_active,
        created_at=agent.created_at,
        is_online=False,
        poll_interval=agent.poll_interval,
        log_level=agent.log_level,
        available_printers=agent.available_printers,
        config_version=agent.config_version,
        api_key=api_key,
    )


@router.get("/agents", response_model=list[PrintAgentResponse])
async def list_print_agents(
    svc: Annotated[PrintService, Depends(get_print_svc)],
    include_inactive: bool = Query(False),
):
    """List all print agents for the tenant.

    Args:
        svc: Print service.
        include_inactive: Include inactive agents.

    Returns:
        list[PrintAgentResponse]: List of agents.
    """
    agents = svc.list_agents(include_inactive=include_inactive)
    return [
        PrintAgentResponse(
            id=a.id,
            tenant_id=a.tenant_id,
            name=a.name,
            printer_name=a.printer_name,
            label_format=a.label_format,
            last_seen=a.last_seen,
            is_active=a.is_active,
            created_at=a.created_at,
            is_online=svc.is_agent_online(a),
            poll_interval=a.poll_interval,
            log_level=a.log_level,
            available_printers=a.available_printers,
            config_version=a.config_version,
        )
        for a in agents
    ]


@router.get("/agents/{agent_id}", response_model=PrintAgentResponse)
async def get_print_agent(
    agent_id: str,
    svc: Annotated[PrintService, Depends(get_print_svc)],
):
    """Get a print agent by ID.

    Args:
        agent_id: Agent UUID.
        svc: Print service.

    Returns:
        PrintAgentResponse: Agent details.

    Raises:
        HTTPException: If agent not found.
    """
    agent = svc.get_agent(agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    return PrintAgentResponse(
        id=agent.id,
        tenant_id=agent.tenant_id,
        name=agent.name,
        printer_name=agent.printer_name,
        label_format=agent.label_format,
        last_seen=agent.last_seen,
        is_active=agent.is_active,
        created_at=agent.created_at,
        is_online=svc.is_agent_online(agent),
        poll_interval=agent.poll_interval,
        log_level=agent.log_level,
        available_printers=agent.available_printers,
        config_version=agent.config_version,
    )


@router.patch("/agents/{agent_id}", response_model=PrintAgentResponse)
async def update_print_agent(
    agent_id: str,
    data: PrintAgentUpdate,
    svc: Annotated[PrintService, Depends(get_print_svc)],
):
    """Update a print agent.

    Args:
        agent_id: Agent UUID.
        data: Update data.
        svc: Print service.

    Returns:
        PrintAgentResponse: Updated agent.

    Raises:
        HTTPException: If agent not found.
    """
    agent = svc.update_agent(agent_id, data)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    return PrintAgentResponse(
        id=agent.id,
        tenant_id=agent.tenant_id,
        name=agent.name,
        printer_name=agent.printer_name,
        label_format=agent.label_format,
        last_seen=agent.last_seen,
        is_active=agent.is_active,
        created_at=agent.created_at,
        is_online=svc.is_agent_online(agent),
        poll_interval=agent.poll_interval,
        log_level=agent.log_level,
        available_printers=agent.available_printers,
        config_version=agent.config_version,
    )


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_print_agent(
    agent_id: str,
    svc: Annotated[PrintService, Depends(get_print_svc)],
):
    """Delete a print agent.

    Args:
        agent_id: Agent UUID.
        svc: Print service.

    Raises:
        HTTPException: If agent not found.
    """
    if not svc.delete_agent(agent_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )


@router.get("/agents/status/online")
async def check_agents_online(
    svc: Annotated[PrintService, Depends(get_print_svc)],
):
    """Check if any agent is online.

    Useful for UI to decide whether to show "Print" or "Download PDF".

    Args:
        svc: Print service.

    Returns:
        dict: Online status.
    """
    return {"has_online_agent": svc.has_online_agent()}


# ============================================================================
# Agent Download Endpoint
# ============================================================================

# Mapping of platform names to binary file names and content types
_AGENT_DOWNLOADS = {
    "windows": {"filename": "FlyPrint.exe", "content_type": "application/octet-stream"},
    "macos": {"filename": "FlyPrint.zip", "content_type": "application/zip"},
    "linux": {"filename": "FlyPrint", "content_type": "application/octet-stream"},
}

_DOWNLOADS_DIR = Path(__file__).parent.parent / "static" / "downloads"


@router.get("/agent/download/{platform_name}")
async def download_agent(platform_name: str):
    """Download the FlyPrint agent binary for a platform.

    Args:
        platform_name: One of 'windows', 'macos', 'linux'.

    Returns:
        FileResponse: The binary file.

    Raises:
        HTTPException: If platform invalid or binary not available.
    """
    if platform_name not in _AGENT_DOWNLOADS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid platform. Choose from: {', '.join(_AGENT_DOWNLOADS.keys())}",
        )

    info = _AGENT_DOWNLOADS[platform_name]
    file_path = _DOWNLOADS_DIR / platform_name / info["filename"]

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"FlyPrint binary for {platform_name} is not yet available. "
            "Please install manually using pip: pip install flyprint",
        )

    return FileResponse(
        path=str(file_path),
        filename=info["filename"],
        media_type=info["content_type"],
    )


@router.get("/agent/download-info")
async def get_download_info():
    """Get information about available FlyPrint downloads.

    Returns:
        dict: Available platforms and their download status.
    """
    platforms = {}
    for plat, info in _AGENT_DOWNLOADS.items():
        file_path = _DOWNLOADS_DIR / plat / info["filename"]
        platforms[plat] = {
            "filename": info["filename"],
            "available": file_path.exists(),
            "size_bytes": file_path.stat().st_size if file_path.exists() else None,
        }
    return {"platforms": platforms}


# ============================================================================
# Pairing Endpoints
# ============================================================================


@router.post("/pairing", response_model=PairingSessionResponse)
async def create_pairing_session(
    request: Request,
    tenant_id: CurrentTenantId,
):
    """Create a pairing session for a new agent.

    Admin clicks "Add Agent" to start pairing. Captures admin's IP
    for zero-config matching. Agent name will come from the agent's
    hostname during pairing.

    Args:
        request: HTTP request (for IP extraction).
        tenant_id: Current tenant ID.

    Returns:
        PairingSessionResponse: Session with code and ID for polling.
    """
    admin_ip = request.client.host if request.client else ""
    session = PrintService.create_pairing_session(
        tenant_id=str(tenant_id),
        admin_ip=admin_ip,
    )
    return PairingSessionResponse(
        session_id=session["id"],
        code=session["code"],
        status=session["status"],
    )


@router.get("/pairing/{session_id}", response_model=PairingSessionResponse)
async def get_pairing_status(
    session_id: str,
    tenant_id: CurrentTenantId,
):
    """Poll pairing session status.

    UI polls this every 2 seconds to check if agent has paired.

    Args:
        session_id: Pairing session ID.
        tenant_id: Current tenant ID.

    Returns:
        PairingSessionResponse: Current session status.

    Raises:
        HTTPException: If session not found.
    """
    session = PrintService.get_pairing_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pairing session not found or expired",
        )

    # Verify tenant owns this session
    if session["tenant_id"] != str(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pairing session not found",
        )

    return PairingSessionResponse(
        session_id=session["id"],
        code=session["code"],
        status=session["status"],
        agent_id=session["agent_id"],
        api_key=session["api_key"],
        agent_name=session["agent_name"],
    )


@router.post("/agent/pair", response_model=AgentPairResponse)
async def agent_pair(
    data: AgentPairRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    """Agent pairing endpoint (unauthenticated).

    Called by `flyprint pair` command. Matches to a waiting pairing
    session by code or by IP address.

    Args:
        data: Pairing request with optional code and hostname.
        request: HTTP request (for IP extraction).
        db: Database session.

    Returns:
        AgentPairResponse: API key and agent info on success.

    Raises:
        HTTPException: If no matching session found.
    """
    agent_ip = request.client.host if request.client else ""
    svc = PrintService(db, tenant_id="")

    result = svc.complete_pairing(
        code=data.code,
        agent_ip=agent_ip,
        hostname=data.hostname,
        available_printers=data.available_printers,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No matching pairing session found. "
            "Make sure 'Add Agent' is active in the web UI, "
            "or provide the pairing code.",
        )

    return AgentPairResponse(**result)


# ============================================================================
# Print Job Endpoints (User facing)
# ============================================================================


@router.post("/print", response_model=PrintJobResponse)
async def create_print_job(
    data: PrintJobCreate,
    svc: Annotated[PrintService, Depends(get_print_svc)],
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
    user_id: CurrentUserId,
):
    """Create a new print job.

    The job will be picked up by an available print agent.
    Optionally records a flip event for each stock if record_flip is True.

    Args:
        data: Job creation data.
        svc: Print service.
        db: Database session.
        tenant_id: Current tenant ID.
        user_id: Current user ID.

    Returns:
        PrintJobResponse: Created job.
    """
    # Record flip events if requested
    if data.record_flip:
        from app.flips.schemas import FlipEventCreate
        from app.flips.service import get_flip_service

        flip_service = get_flip_service(db, str(tenant_id), str(user_id) if user_id else None)
        for stock_id in data.stock_ids:
            flip_service.record_flip(FlipEventCreate(stock_id=stock_id))

    job = svc.create_job(data)
    return PrintJobResponse.model_validate(job)


@router.get("/jobs", response_model=list[PrintJobResponse])
async def list_print_jobs(
    svc: Annotated[PrintService, Depends(get_print_svc)],
    status_filter: PrintJobStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
):
    """List print jobs for the tenant.

    Args:
        svc: Print service.
        status_filter: Filter by status.
        limit: Maximum jobs to return.

    Returns:
        list[PrintJobResponse]: List of jobs.
    """
    jobs = svc.list_jobs(status=status_filter, limit=limit)
    return [PrintJobResponse.model_validate(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=PrintJobResponse)
async def get_print_job(
    job_id: str,
    svc: Annotated[PrintService, Depends(get_print_svc)],
):
    """Get a print job by ID.

    Args:
        job_id: Job UUID.
        svc: Print service.

    Returns:
        PrintJobResponse: Job details.

    Raises:
        HTTPException: If job not found.
    """
    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    return PrintJobResponse.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=PrintJobResponse)
async def cancel_print_job(
    job_id: str,
    svc: Annotated[PrintService, Depends(get_print_svc)],
):
    """Cancel a pending print job.

    Args:
        job_id: Job UUID.
        svc: Print service.

    Returns:
        PrintJobResponse: Cancelled job.

    Raises:
        HTTPException: If job not found or not cancellable.
    """
    job = svc.cancel_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job not found or cannot be cancelled",
        )
    return PrintJobResponse.model_validate(job)


@router.get("/jobs/statistics")
async def get_job_statistics(
    svc: Annotated[PrintService, Depends(get_print_svc)],
):
    """Get print job statistics.

    Args:
        svc: Print service.

    Returns:
        dict: Job counts by status.
    """
    return svc.get_job_statistics()


# ============================================================================
# Agent API Endpoints (For print agents to call)
# ============================================================================

# Latest FlyPrint agent version - update when releasing new builds
LATEST_AGENT_VERSION = "0.1.0"


@router.post("/agent/heartbeat", response_model=PrintAgentHeartbeatResponse)
async def agent_heartbeat(
    data: PrintAgentHeartbeat,
    auth: Annotated[tuple[PrintService, str], Depends(get_agent_from_api_key)],
):
    """Agent heartbeat - updates last_seen and optionally printer info.

    Called by agents to indicate they are online. Returns config_version
    so agents can detect when config has changed.

    Args:
        data: Heartbeat data.
        auth: Authenticated agent.

    Returns:
        PrintAgentHeartbeatResponse: Status and config_version.
    """
    svc, agent_id = auth
    agent = svc.update_agent_heartbeat(
        agent_id,
        printer_name=data.printer_name,
        available_printers=data.available_printers,
    )
    config_version = agent.config_version if agent else 1
    return PrintAgentHeartbeatResponse(
        status="ok",
        config_version=config_version,
        latest_agent_version=LATEST_AGENT_VERSION,
    )


@router.get("/agent/config", response_model=PrintAgentConfigResponse)
async def get_agent_config(
    auth: Annotated[tuple[PrintService, str], Depends(get_agent_from_api_key)],
):
    """Get merged config for the authenticated agent.

    Returns tenant-level defaults merged with agent-specific settings.
    Agents fetch this when config_version changes.

    Args:
        auth: Authenticated agent.

    Returns:
        PrintAgentConfigResponse: Merged configuration.

    Raises:
        HTTPException: If config not found.
    """
    svc, agent_id = auth
    config = svc.get_agent_config(agent_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent config not found",
        )
    return PrintAgentConfigResponse(**config)


@router.get("/agent/jobs", response_model=list[PrintJobResponse])
async def get_pending_jobs_for_agent(
    auth: Annotated[tuple[PrintService, str], Depends(get_agent_from_api_key)],
):
    """Get pending jobs for the authenticated agent.

    Agents poll this endpoint to find work.

    Args:
        auth: Authenticated agent.

    Returns:
        list[PrintJobResponse]: Pending jobs.
    """
    svc, agent_id = auth
    jobs = svc.get_pending_jobs_for_agent(agent_id)
    return [PrintJobResponse.model_validate(j) for j in jobs]


@router.post("/agent/jobs/{job_id}/claim", response_model=PrintJobResponse)
async def claim_print_job(
    job_id: str,
    auth: Annotated[tuple[PrintService, str], Depends(get_agent_from_api_key)],
):
    """Claim a print job for processing.

    Args:
        job_id: Job UUID.
        auth: Authenticated agent.

    Returns:
        PrintJobResponse: Claimed job.

    Raises:
        HTTPException: If job not found or already claimed.
    """
    svc, agent_id = auth
    job = svc.claim_job(job_id, agent_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job not found or already claimed",
        )
    return PrintJobResponse.model_validate(job)


@router.get("/agent/jobs/{job_id}/labels", response_model=PrintJobLabels)
async def get_job_labels(
    job_id: str,
    auth: Annotated[tuple[PrintService, str], Depends(get_agent_from_api_key)],
):
    """Get label data for a print job.

    Agents call this to get the actual content to print.

    Args:
        job_id: Job UUID.
        auth: Authenticated agent.

    Returns:
        PrintJobLabels: Job with label data.

    Raises:
        HTTPException: If job not found.
    """
    svc, agent_id = auth
    labels = svc.get_job_labels(job_id)
    if not labels:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    return labels


@router.get("/agent/jobs/{job_id}/pdf")
async def get_job_pdf(
    job_id: str,
    auth: Annotated[tuple[PrintService, str], Depends(get_agent_from_api_key)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get PDF for a print job.

    Agents call this to get the PDF to send to printer.

    Args:
        job_id: Job UUID.
        auth: Authenticated agent.
        db: Database session.

    Returns:
        Response: PDF file.

    Raises:
        HTTPException: If job not found.
    """
    svc, agent_id = auth
    labels = svc.get_job_labels(job_id)
    if not labels:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Get the job to find tenant_id for label service
    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Check if this is a test label job
    if job.stock_ids == ["__TEST__"]:
        from app.labels.pdf_generator import create_test_label_pdf

        pdf_data = create_test_label_pdf(label_format=job.label_format)
    else:
        # Generate PDF using label service
        from app.labels.pdf_generator import create_batch_label_pdf

        label_data = [
            {
                "stock_id": label.stock_id,
                "genotype": label.genotype,
                "source_info": label.source_info,
                "location_info": label.location_info,
                "print_date": label.print_date,
            }
            for label in labels.labels
        ]

        pdf_data = create_batch_label_pdf(
            label_data,
            label_format=labels.label_format,
            code_type=labels.code_type,
        )

    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=job_{job_id}.pdf",
        },
    )


@router.get("/agent/jobs/{job_id}/image")
async def get_job_image(
    job_id: str,
    auth: Annotated[tuple[PrintService, str], Depends(get_agent_from_api_key)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get PNG image for a print job.

    PNG format works better with Dymo printers (avoids CUPS PDF scaling issues).

    Args:
        job_id: Job UUID.
        auth: Authenticated agent.
        db: Database session.

    Returns:
        Response: PNG image file.

    Raises:
        HTTPException: If job not found.
    """
    svc, agent_id = auth
    labels = svc.get_job_labels(job_id)
    if not labels:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Get the job to find label format
    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Check if this is a test label job
    if job.stock_ids == ["__TEST__"]:
        from app.labels.pdf_generator import create_test_label_png

        png_data = create_test_label_png(label_format=job.label_format)
    else:
        # Generate PNG using label service
        from app.labels.pdf_generator import create_label_png

        # For now, just return the first label as PNG
        # TODO: Support multiple labels by concatenating images
        if labels.labels:
            label = labels.labels[0]
            png_data = create_label_png(
                stock_id=label.stock_id,
                genotype=label.genotype,
                label_format=labels.label_format,
                source_info=label.source_info,
                location_info=label.location_info,
                code_type=labels.code_type,
                print_date=label.print_date,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No labels in job",
            )

    return Response(
        content=png_data,
        media_type="image/png",
        headers={
            "Content-Disposition": f"attachment; filename=job_{job_id}.png",
        },
    )


@router.post("/agent/jobs/{job_id}/start", response_model=PrintJobResponse)
async def start_print_job(
    job_id: str,
    auth: Annotated[tuple[PrintService, str], Depends(get_agent_from_api_key)],
):
    """Mark a job as currently printing.

    Args:
        job_id: Job UUID.
        auth: Authenticated agent.

    Returns:
        PrintJobResponse: Updated job.

    Raises:
        HTTPException: If job not found or wrong status.
    """
    svc, agent_id = auth
    job = svc.start_printing(job_id, agent_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job not found or cannot start",
        )
    return PrintJobResponse.model_validate(job)


@router.post("/agent/jobs/{job_id}/complete", response_model=PrintJobResponse)
async def complete_print_job(
    job_id: str,
    data: PrintJobComplete,
    auth: Annotated[tuple[PrintService, str], Depends(get_agent_from_api_key)],
):
    """Mark a job as completed or failed.

    Args:
        job_id: Job UUID.
        data: Completion data.
        auth: Authenticated agent.

    Returns:
        PrintJobResponse: Updated job.

    Raises:
        HTTPException: If job not found.
    """
    svc, agent_id = auth
    job = svc.complete_job(job_id, agent_id, success=data.success, error_message=data.error_message)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job not found or not owned by agent",
        )
    return PrintJobResponse.model_validate(job)
