"""Print job and agent service layer."""

import secrets
import string
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from app.db.models import PrintAgent, PrintJob, PrintJobStatus, Stock, Tenant
from app.labels.schemas import (
    LabelData,
    PrintAgentCreate,
    PrintAgentUpdate,
    PrintJobCreate,
    PrintJobLabels,
)

# ============================================================================
# In-Memory Pairing Session Store (5-minute TTL)
# ============================================================================

_pairing_sessions: dict[str, dict] = {}

PAIRING_TTL_SECONDS = 300  # 5 minutes


def _generate_pairing_code() -> str:
    """Generate a 6-character alphanumeric pairing code.

    Returns:
        str: Uppercase alphanumeric code like 'AB3K9X'.
    """
    # Reason: Exclude confusing chars (0/O, 1/I/L) for readability
    alphabet = string.ascii_uppercase.replace("O", "").replace("I", "").replace("L", "")
    digits = string.digits.replace("0", "").replace("1", "")
    charset = alphabet + digits
    return "".join(secrets.choice(charset) for _ in range(6))


def _cleanup_expired_sessions() -> None:
    """Remove expired pairing sessions from memory."""
    now = datetime.utcnow()
    expired = [sid for sid, s in _pairing_sessions.items() if s["expires_at"] < now]
    for sid in expired:
        del _pairing_sessions[sid]


class PrintService:
    """Service class for print job and agent operations."""

    # Agent is considered online if seen within this many seconds
    ONLINE_THRESHOLD_SECONDS = 60

    def __init__(self, db: Session, tenant_id: str, user_id: str | None = None):
        """Initialize print service.

        Args:
            db: Database session.
            tenant_id: Current tenant ID.
            user_id: Current user ID (optional).
        """
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    # ========================================================================
    # Print Agent Methods
    # ========================================================================

    def create_agent(self, data: PrintAgentCreate) -> tuple[PrintAgent, str]:
        """Create a new print agent.

        Args:
            data: Agent creation data.

        Returns:
            tuple[PrintAgent, str]: Created agent and API key.
        """
        api_key = secrets.token_urlsafe(32)  # 43 chars

        agent = PrintAgent(
            tenant_id=self.tenant_id,
            name=data.name,
            api_key=api_key,
            printer_name=data.printer_name,
            label_format=data.label_format,
            poll_interval=data.poll_interval,
            log_level=data.log_level,
        )
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)

        return agent, api_key

    def get_agent(self, agent_id: str) -> PrintAgent | None:
        """Get a print agent by ID.

        Args:
            agent_id: Agent UUID.

        Returns:
            PrintAgent | None: Agent if found.
        """
        return (
            self.db.query(PrintAgent)
            .filter(PrintAgent.id == agent_id, PrintAgent.tenant_id == self.tenant_id)
            .first()
        )

    def get_agent_by_api_key(self, api_key: str) -> PrintAgent | None:
        """Get a print agent by API key.

        Args:
            api_key: Agent API key.

        Returns:
            PrintAgent | None: Agent if found and active.
        """
        return (
            self.db.query(PrintAgent)
            .filter(PrintAgent.api_key == api_key, PrintAgent.is_active.is_(True))
            .first()
        )

    def list_agents(self, include_inactive: bool = False) -> list[PrintAgent]:
        """List all print agents for the tenant.

        Args:
            include_inactive: Whether to include inactive agents.

        Returns:
            list[PrintAgent]: List of agents.
        """
        query = self.db.query(PrintAgent).filter(PrintAgent.tenant_id == self.tenant_id)
        if not include_inactive:
            query = query.filter(PrintAgent.is_active.is_(True))
        return query.order_by(PrintAgent.created_at.desc()).all()

    def update_agent(self, agent_id: str, data: PrintAgentUpdate) -> PrintAgent | None:
        """Update a print agent.

        Increments config_version when config-relevant fields change.

        Args:
            agent_id: Agent UUID.
            data: Update data.

        Returns:
            PrintAgent | None: Updated agent if found.
        """
        agent = self.get_agent(agent_id)
        if not agent:
            return None

        update_data = data.model_dump(exclude_unset=True)
        config_fields = {"printer_name", "label_format", "poll_interval", "log_level"}
        config_changed = any(k in config_fields for k in update_data)

        for key, value in update_data.items():
            setattr(agent, key, value)

        if config_changed:
            agent.config_version += 1

        self.db.commit()
        self.db.refresh(agent)
        return agent

    def delete_agent(self, agent_id: str) -> bool:
        """Delete a print agent.

        Args:
            agent_id: Agent UUID.

        Returns:
            bool: True if deleted.
        """
        agent = self.get_agent(agent_id)
        if not agent:
            return False

        self.db.delete(agent)
        self.db.commit()
        return True

    def update_agent_heartbeat(
        self,
        agent_id: str,
        printer_name: str | None = None,
        available_printers: list[dict] | None = None,
    ) -> PrintAgent | None:
        """Update agent last_seen timestamp (heartbeat).

        Args:
            agent_id: Agent UUID.
            printer_name: Optional printer name update.
            available_printers: Optional list of available printers from agent.

        Returns:
            PrintAgent | None: Updated agent if found.
        """
        agent = self.db.query(PrintAgent).filter(PrintAgent.id == agent_id).first()
        if not agent:
            return None

        agent.last_seen = datetime.utcnow()
        if printer_name is not None:
            agent.printer_name = printer_name
        if available_printers is not None:
            agent.available_printers = available_printers

        self.db.commit()
        self.db.refresh(agent)
        return agent

    def is_agent_online(self, agent: PrintAgent) -> bool:
        """Check if agent is considered online.

        Args:
            agent: Print agent.

        Returns:
            bool: True if online.
        """
        if not agent.last_seen:
            return False
        threshold = datetime.utcnow() - timedelta(seconds=self.ONLINE_THRESHOLD_SECONDS)
        return agent.last_seen > threshold

    def has_online_agent(self) -> bool:
        """Check if tenant has any online agents.

        Returns:
            bool: True if at least one agent is online.
        """
        threshold = datetime.utcnow() - timedelta(seconds=self.ONLINE_THRESHOLD_SECONDS)
        return (
            self.db.query(PrintAgent)
            .filter(
                PrintAgent.tenant_id == self.tenant_id,
                PrintAgent.is_active.is_(True),
                PrintAgent.last_seen > threshold,
            )
            .first()
            is not None
        )

    def get_agent_config(self, agent_id: str) -> dict | None:
        """Get merged config for an agent (tenant defaults + agent settings).

        Args:
            agent_id: Agent UUID.

        Returns:
            dict | None: Merged config or None if agent not found.
        """
        agent = self.db.query(PrintAgent).filter(PrintAgent.id == agent_id).first()
        if not agent:
            return None

        tenant = self.db.query(Tenant).filter(Tenant.id == agent.tenant_id).first()
        if not tenant:
            return None

        from app.labels.pdf_generator import LABEL_FORMATS

        fmt = LABEL_FORMATS.get(tenant.default_label_format, {})

        return {
            "printer_name": agent.printer_name,
            "label_format": tenant.default_label_format,
            "code_type": tenant.default_code_type,
            "copies": tenant.default_copies,
            "orientation": tenant.default_orientation,
            "poll_interval": agent.poll_interval,
            "log_level": agent.log_level,
            "config_version": agent.config_version,
            "cups_page": fmt.get("cups_page", "w72h154"),
        }

    # ========================================================================
    # Pairing Methods
    # ========================================================================

    @staticmethod
    def create_pairing_session(tenant_id: str, admin_ip: str) -> dict:
        """Create a new pairing session.

        Args:
            tenant_id: Tenant UUID.
            admin_ip: IP address of the admin's browser.

        Returns:
            dict: Created pairing session.
        """
        _cleanup_expired_sessions()

        session_id = secrets.token_urlsafe(16)
        code = _generate_pairing_code()

        session = {
            "id": session_id,
            "code": code,
            "tenant_id": tenant_id,
            "admin_ip": admin_ip,
            "expires_at": datetime.utcnow() + timedelta(seconds=PAIRING_TTL_SECONDS),
            "status": "waiting",
            "agent_id": None,
            "api_key": None,
            "agent_name": None,
        }
        _pairing_sessions[session_id] = session
        return session

    @staticmethod
    def get_pairing_session(session_id: str) -> dict | None:
        """Get a pairing session by ID.

        Args:
            session_id: Session ID.

        Returns:
            dict | None: Session if found and not expired.
        """
        _cleanup_expired_sessions()
        session = _pairing_sessions.get(session_id)
        if not session:
            return None
        if session["expires_at"] < datetime.utcnow():
            session["status"] = "expired"
        return session

    def complete_pairing(
        self,
        code: str | None,
        agent_ip: str,
        hostname: str | None = None,
        available_printers: list[dict] | None = None,
    ) -> dict | None:
        """Match a pairing request to a session and create the agent.

        Tries code-based match first (if code provided), then IP-based.

        Args:
            code: Optional pairing code.
            agent_ip: IP address of the agent machine.
            hostname: Optional hostname for agent name.
            available_printers: Optional list of available printers.

        Returns:
            dict | None: Pairing result with api_key, or None if no match.
        """
        _cleanup_expired_sessions()
        now = datetime.utcnow()

        matched_session = None

        if code:
            # Code-based matching
            code_upper = code.upper()
            for session in _pairing_sessions.values():
                if (
                    session["status"] == "waiting"
                    and session["code"] == code_upper
                    and session["expires_at"] > now
                ):
                    matched_session = session
                    break
        else:
            # IP-based matching
            for session in _pairing_sessions.values():
                if (
                    session["status"] == "waiting"
                    and session["admin_ip"] == agent_ip
                    and session["expires_at"] > now
                ):
                    matched_session = session
                    break

        if not matched_session:
            return None

        # Create the agent in this tenant's context
        self.tenant_id = matched_session["tenant_id"]
        agent_name = hostname or "FlyPush Printing Agent"
        agent_data = PrintAgentCreate(name=agent_name)
        agent, api_key = self.create_agent(agent_data)

        # Update available_printers if provided
        if available_printers:
            agent.available_printers = available_printers
            self.db.commit()
            self.db.refresh(agent)

        # Mark session as completed
        matched_session["status"] = "completed"
        matched_session["agent_id"] = agent.id
        matched_session["api_key"] = api_key
        matched_session["agent_name"] = agent_name

        return {
            "api_key": api_key,
            "agent_name": agent_name,
            "agent_id": agent.id,
        }

    # ========================================================================
    # Print Job Methods
    # ========================================================================

    def create_job(self, data: PrintJobCreate) -> PrintJob:
        """Create a new print job.

        Args:
            data: Job creation data.

        Returns:
            PrintJob: Created job.
        """
        job = PrintJob(
            tenant_id=self.tenant_id,
            created_by_id=self.user_id,
            stock_ids=data.stock_ids,
            label_format=data.label_format,
            copies=data.copies,
            code_type=data.code_type,
            status=PrintJobStatus.PENDING,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def create_test_job(self, label_format: str = "dymo_11352") -> PrintJob:
        """Create a test print job to verify alignment.

        Args:
            label_format: Label format key.

        Returns:
            PrintJob: Created test job.
        """
        job = PrintJob(
            tenant_id=self.tenant_id,
            created_by_id=self.user_id,
            stock_ids=["__TEST__"],  # Special marker for test labels
            label_format=label_format,
            copies=1,
            status=PrintJobStatus.PENDING,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_job(self, job_id: str) -> PrintJob | None:
        """Get a print job by ID.

        Args:
            job_id: Job UUID.

        Returns:
            PrintJob | None: Job if found.
        """
        return (
            self.db.query(PrintJob)
            .filter(PrintJob.id == job_id, PrintJob.tenant_id == self.tenant_id)
            .first()
        )

    def list_jobs(
        self,
        status: PrintJobStatus | None = None,
        limit: int = 50,
    ) -> list[PrintJob]:
        """List print jobs for the tenant.

        Args:
            status: Filter by status.
            limit: Maximum jobs to return.

        Returns:
            list[PrintJob]: List of jobs.
        """
        query = self.db.query(PrintJob).filter(PrintJob.tenant_id == self.tenant_id)
        if status:
            query = query.filter(PrintJob.status == status)
        return query.order_by(PrintJob.created_at.desc()).limit(limit).all()

    def get_pending_jobs_for_agent(self, agent_id: str) -> list[PrintJob]:
        """Get pending jobs that an agent can claim.

        Args:
            agent_id: Agent UUID.

        Returns:
            list[PrintJob]: List of pending jobs.
        """
        agent = self.db.query(PrintAgent).filter(PrintAgent.id == agent_id).first()
        if not agent:
            return []

        return (
            self.db.query(PrintJob)
            .filter(
                PrintJob.tenant_id == agent.tenant_id,
                PrintJob.status == PrintJobStatus.PENDING,
            )
            .order_by(PrintJob.created_at.asc())
            .all()
        )

    def claim_job(self, job_id: str, agent_id: str) -> PrintJob | None:
        """Claim a print job for an agent.

        Args:
            job_id: Job UUID.
            agent_id: Agent UUID.

        Returns:
            PrintJob | None: Claimed job, or None if not claimable.
        """
        job = self.db.query(PrintJob).filter(PrintJob.id == job_id).first()
        if not job or job.status != PrintJobStatus.PENDING:
            return None

        # Verify agent belongs to same tenant
        agent = self.db.query(PrintAgent).filter(PrintAgent.id == agent_id).first()
        if not agent or agent.tenant_id != job.tenant_id:
            return None

        job.agent_id = agent_id
        job.status = PrintJobStatus.CLAIMED
        job.claimed_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(job)
        return job

    def start_printing(self, job_id: str, agent_id: str) -> PrintJob | None:
        """Mark a job as currently printing.

        Args:
            job_id: Job UUID.
            agent_id: Agent UUID.

        Returns:
            PrintJob | None: Updated job.
        """
        job = self.db.query(PrintJob).filter(PrintJob.id == job_id).first()
        if not job or job.agent_id != agent_id:
            return None
        if job.status not in (PrintJobStatus.CLAIMED, PrintJobStatus.PENDING):
            return None

        job.status = PrintJobStatus.PRINTING
        self.db.commit()
        self.db.refresh(job)
        return job

    def complete_job(
        self,
        job_id: str,
        agent_id: str,
        success: bool = True,
        error_message: str | None = None,
    ) -> PrintJob | None:
        """Mark a job as completed or failed.

        Args:
            job_id: Job UUID.
            agent_id: Agent UUID.
            success: Whether print succeeded.
            error_message: Error message if failed.

        Returns:
            PrintJob | None: Updated job.
        """
        job = self.db.query(PrintJob).filter(PrintJob.id == job_id).first()
        if not job or job.agent_id != agent_id:
            return None

        job.status = PrintJobStatus.COMPLETED if success else PrintJobStatus.FAILED
        job.completed_at = datetime.utcnow()
        job.error_message = error_message

        self.db.commit()
        self.db.refresh(job)
        return job

    def cancel_job(self, job_id: str) -> PrintJob | None:
        """Cancel a print job.

        Args:
            job_id: Job UUID.

        Returns:
            PrintJob | None: Cancelled job, or None if not cancellable.
        """
        job = self.get_job(job_id)
        if not job:
            return None

        # Can only cancel pending or claimed jobs
        if job.status not in (PrintJobStatus.PENDING, PrintJobStatus.CLAIMED):
            return None

        job.status = PrintJobStatus.CANCELLED
        job.completed_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(job)
        return job

    def get_job_labels(self, job_id: str) -> PrintJobLabels | None:
        """Get label data for a print job.

        Used by agents to get the actual label content.

        Args:
            job_id: Job UUID.

        Returns:
            PrintJobLabels | None: Job with label data.
        """
        job = self.db.query(PrintJob).filter(PrintJob.id == job_id).first()
        if not job:
            return None

        # Handle test label jobs
        if job.stock_ids == ["__TEST__"]:
            return PrintJobLabels(
                job_id=job.id,
                label_format=job.label_format,
                copies=job.copies,
                code_type=job.code_type,
                labels=[
                    LabelData(
                        stock_id="TEST",
                        genotype="Test Label",
                        source_info=None,
                        location_info=None,
                        print_date=date.today().isoformat(),
                    )
                ],
            )

        # Fetch stocks
        stocks = (
            self.db.query(Stock)
            .options(joinedload(Stock.tray))
            .filter(Stock.id.in_(job.stock_ids))
            .all()
        )

        labels = []
        for stock in stocks:
            # Build source info
            source_info = None
            if stock.origin.value == "repository" and stock.repository:
                source_info = f"{stock.repository.value.upper()} #{stock.repository_stock_id or ''}"
            elif stock.origin.value == "external" and stock.external_source:
                source_info = f"From: {stock.external_source}"

            # Build location info
            location_info = None
            if stock.tray:
                location_info = stock.tray.name
                if stock.position:
                    location_info += f" - {stock.position}"

            labels.append(
                LabelData(
                    stock_id=stock.stock_id,
                    genotype=stock.genotype,
                    source_info=source_info,
                    location_info=location_info,
                    print_date=date.today().isoformat(),
                )
            )

        return PrintJobLabels(
            job_id=job.id,
            label_format=job.label_format,
            copies=job.copies,
            code_type=job.code_type,
            labels=labels,
        )

    def get_job_statistics(self) -> dict:
        """Get print job statistics for the tenant.

        Returns:
            dict: Job counts by status.
        """
        from sqlalchemy import func

        results = (
            self.db.query(PrintJob.status, func.count(PrintJob.id))
            .filter(PrintJob.tenant_id == self.tenant_id)
            .group_by(PrintJob.status)
            .all()
        )

        stats = {status.value: 0 for status in PrintJobStatus}
        for status, count in results:
            stats[status.value] = count

        return stats


def get_print_service(db: Session, tenant_id: str, user_id: str | None = None) -> PrintService:
    """Factory function for PrintService.

    Args:
        db: Database session.
        tenant_id: Tenant ID.
        user_id: User ID (optional).

    Returns:
        PrintService: Print service instance.
    """
    return PrintService(db, tenant_id, user_id)
