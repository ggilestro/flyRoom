"""Schemas for label printing system."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class PrintJobStatus(str, Enum):
    """Print job status."""

    PENDING = "pending"
    CLAIMED = "claimed"
    PRINTING = "printing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ============================================================================
# Print Agent Schemas
# ============================================================================


class PrintAgentCreate(BaseModel):
    """Schema for creating a print agent."""

    name: str = Field(..., min_length=1, max_length=100, description="Agent display name")
    printer_name: str | None = Field(None, max_length=100, description="CUPS printer name")
    label_format: str = Field("dymo_11352", description="Default label format")
    poll_interval: int = Field(5, ge=1, le=60, description="Poll interval in seconds")
    log_level: str = Field("INFO", description="Log level")


class PrintAgentUpdate(BaseModel):
    """Schema for updating a print agent."""

    name: str | None = Field(None, min_length=1, max_length=100)
    printer_name: str | None = None
    label_format: str | None = None
    is_active: bool | None = None
    poll_interval: int | None = Field(None, ge=1, le=60)
    log_level: str | None = Field(None, pattern="^(DEBUG|INFO|WARNING|ERROR)$")


class PrintAgentResponse(BaseModel):
    """Schema for print agent response."""

    id: str
    tenant_id: str
    name: str
    printer_name: str | None
    label_format: str
    last_seen: datetime | None
    is_active: bool
    created_at: datetime
    is_online: bool = Field(
        default=False, description="Whether agent has been seen in last 60 seconds"
    )
    poll_interval: int = 5
    log_level: str = "INFO"
    available_printers: list | None = None
    config_version: int = 1

    model_config = {"from_attributes": True}


class PrintAgentWithKey(PrintAgentResponse):
    """Schema for print agent with API key (only on creation)."""

    api_key: str


class PrintAgentHeartbeat(BaseModel):
    """Schema for agent heartbeat/status update."""

    printer_name: str | None = None
    printer_status: str | None = None  # e.g., "ready", "offline", "paper_out"
    available_printers: list[dict] | None = None


class PrintAgentHeartbeatResponse(BaseModel):
    """Schema for heartbeat response with config version."""

    status: str = "ok"
    config_version: int
    latest_agent_version: str | None = None


class PrintAgentConfigResponse(BaseModel):
    """Schema for merged agent config (tenant + agent settings)."""

    printer_name: str | None
    label_format: str
    code_type: str
    copies: int
    orientation: int
    poll_interval: int
    log_level: str
    config_version: int
    cups_page: str = "w72h154"


# ============================================================================
# Pairing Schemas
# ============================================================================


class PairingSessionResponse(BaseModel):
    """Schema for pairing session status."""

    session_id: str
    code: str
    status: str  # waiting | completed | expired
    agent_id: str | None = None
    api_key: str | None = None
    agent_name: str | None = None


class AgentPairRequest(BaseModel):
    """Schema for agent pairing request."""

    code: str | None = Field(None, description="6-char pairing code (fallback)")
    hostname: str | None = Field(None, max_length=255, description="Agent machine hostname")
    available_printers: list[dict] | None = None


class AgentPairResponse(BaseModel):
    """Schema for successful pairing response."""

    api_key: str
    agent_name: str
    agent_id: str


# ============================================================================
# Print Job Schemas
# ============================================================================


class PrintJobCreate(BaseModel):
    """Schema for creating a print job."""

    stock_ids: list[str] = Field(..., min_length=1, description="List of stock UUIDs to print")
    label_format: str = Field("dymo_11352", description="Label format to use")
    copies: int = Field(1, ge=1, le=10, description="Copies per label")
    code_type: str = Field("qr", description="Code type: 'qr' or 'barcode'")
    record_flip: bool = Field(False, description="Record a flip event for each stock")


class PrintTrayLabelRequest(BaseModel):
    """Schema for printing a tray label."""

    tray_id: str
    label_format: str = "dymo_11352"
    code_type: str = "qr"


class PrintJobResponse(BaseModel):
    """Schema for print job response."""

    id: str
    tenant_id: str
    agent_id: str | None
    created_by_id: str | None
    status: PrintJobStatus
    stock_ids: list[str]
    label_format: str
    copies: int
    code_type: str = "qr"
    created_at: datetime
    claimed_at: datetime | None
    completed_at: datetime | None
    error_message: str | None

    model_config = {"from_attributes": True}


class PrintJobUpdate(BaseModel):
    """Schema for updating a print job (agent use)."""

    status: PrintJobStatus | None = None
    error_message: str | None = None


class PrintJobClaim(BaseModel):
    """Schema for agent claiming a job."""

    agent_id: str


class PrintJobComplete(BaseModel):
    """Schema for marking a job complete or failed."""

    success: bool = True
    error_message: str | None = None


# ============================================================================
# Label Data Schemas
# ============================================================================


class LabelData(BaseModel):
    """Schema for label data returned to agents."""

    stock_id: str
    genotype: str
    source_info: str | None = None
    location_info: str | None = None
    print_date: str | None = None
    qr_content: str | None = None  # Override QR code content (e.g. for tray labels)


class PrintJobLabels(BaseModel):
    """Schema for print job with label data (for agents)."""

    job_id: str
    label_format: str
    copies: int
    code_type: str = "qr"
    labels: list[LabelData]


# ============================================================================
# Label Format Schemas
# ============================================================================


class LabelFormat(BaseModel):
    """Schema for label format info."""

    id: str
    name: str
    width_mm: float
    height_mm: float
    description: str | None = None
    supports_pdf: bool = True
