"""FlyPrint agent - polls server for print jobs and prints them."""

import logging
import signal
import sys
import time
from datetime import datetime

import requests

from flyprint.config import FlyPrintConfig, get_config
from flyprint.printer import PrinterError, get_printer

logger = logging.getLogger(__name__)


class FlyPrintAgent:
    """Print agent that polls server for jobs and prints via CUPS.

    The agent:
    1. Sends heartbeats to the server to indicate it's online
    2. Polls for pending print jobs
    3. Claims jobs, downloads PDFs, and prints them
    4. Reports job completion/failure back to server
    """

    def __init__(self, config: FlyPrintConfig | None = None):
        """Initialize the agent.

        Args:
            config: Configuration (loads from file if not provided).
        """
        self.config = config or get_config()
        self.printer = get_printer(self.config.printer_name)
        self.running = False
        self._last_heartbeat = None

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info("Shutdown signal received")
        self.running = False

    @property
    def _headers(self) -> dict:
        """Get API request headers with authentication."""
        return {
            "X-API-Key": self.config.api_key,
            "Content-Type": "application/json",
        }

    def _api_url(self, path: str) -> str:
        """Build full API URL.

        Args:
            path: API path (e.g., '/agent/heartbeat').

        Returns:
            str: Full URL.
        """
        base = self.config.server_url.rstrip("/")
        return f"{base}/api/labels{path}"

    def send_heartbeat(self) -> bool:
        """Send heartbeat to server.

        Returns:
            bool: True if heartbeat was successful.
        """
        try:
            printer_status = self.printer.get_printer_status()
            response = requests.post(
                self._api_url("/agent/heartbeat"),
                headers=self._headers,
                json={
                    "printer_name": self.config.printer_name,
                    "printer_status": printer_status,
                },
                timeout=10,
            )
            if response.status_code == 200:
                self._last_heartbeat = datetime.utcnow()
                return True
            else:
                logger.warning(f"Heartbeat failed: {response.status_code}")
                return False
        except requests.RequestException as e:
            logger.error(f"Heartbeat error: {e}")
            return False

    def get_pending_jobs(self) -> list[dict]:
        """Get pending print jobs from server.

        Returns:
            list[dict]: List of pending jobs.
        """
        try:
            response = requests.get(
                self._api_url("/agent/jobs"),
                headers=self._headers,
                timeout=10,
            )
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Failed to get jobs: {response.status_code}")
                return []
        except requests.RequestException as e:
            logger.error(f"Error getting jobs: {e}")
            return []

    def claim_job(self, job_id: str) -> dict | None:
        """Claim a print job.

        Args:
            job_id: Job UUID.

        Returns:
            dict | None: Claimed job or None if failed.
        """
        try:
            response = requests.post(
                self._api_url(f"/agent/jobs/{job_id}/claim"),
                headers=self._headers,
                timeout=10,
            )
            if response.status_code == 200:
                logger.info(f"Claimed job {job_id}")
                return response.json()
            else:
                logger.warning(f"Failed to claim job {job_id}: {response.status_code}")
                return None
        except requests.RequestException as e:
            logger.error(f"Error claiming job: {e}")
            return None

    def get_job_pdf(self, job_id: str) -> bytes | None:
        """Download PDF for a print job.

        Args:
            job_id: Job UUID.

        Returns:
            bytes | None: PDF data or None if failed.
        """
        try:
            response = requests.get(
                self._api_url(f"/agent/jobs/{job_id}/pdf"),
                headers=self._headers,
                timeout=30,
            )
            if response.status_code == 200:
                return response.content
            else:
                logger.warning(f"Failed to get PDF for job {job_id}: {response.status_code}")
                return None
        except requests.RequestException as e:
            logger.error(f"Error getting PDF: {e}")
            return None

    def get_job_image(self, job_id: str) -> tuple[bytes, str] | None:
        """Download label image for a print job.

        Requests PNG format which works better with Dymo printers.

        Args:
            job_id: Job UUID.

        Returns:
            tuple[bytes, str] | None: (image data, content_type) or None if failed.
        """
        try:
            # Request PNG format for Dymo printers
            response = requests.get(
                self._api_url(f"/agent/jobs/{job_id}/image"),
                headers=self._headers,
                timeout=30,
            )
            if response.status_code == 200:
                content_type = response.headers.get("content-type", "image/png")
                return response.content, content_type
            else:
                logger.warning(f"Failed to get image for job {job_id}: {response.status_code}")
                return None
        except requests.RequestException as e:
            logger.error(f"Error getting image: {e}")
            return None

    def start_job(self, job_id: str) -> bool:
        """Mark job as printing.

        Args:
            job_id: Job UUID.

        Returns:
            bool: True if successful.
        """
        try:
            response = requests.post(
                self._api_url(f"/agent/jobs/{job_id}/start"),
                headers=self._headers,
                timeout=10,
            )
            return response.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Error starting job: {e}")
            return False

    def complete_job(self, job_id: str, success: bool, error_message: str | None = None) -> bool:
        """Mark job as completed or failed.

        Args:
            job_id: Job UUID.
            success: Whether printing succeeded.
            error_message: Error message if failed.

        Returns:
            bool: True if successful.
        """
        try:
            response = requests.post(
                self._api_url(f"/agent/jobs/{job_id}/complete"),
                headers=self._headers,
                json={"success": success, "error_message": error_message},
                timeout=10,
            )
            return response.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Error completing job: {e}")
            return False

    def process_job(self, job: dict) -> bool:
        """Process a single print job.

        Args:
            job: Job data from server.

        Returns:
            bool: True if job was processed successfully.
        """
        job_id = job["id"]
        copies = job.get("copies", 1)

        logger.info(
            f"Processing job {job_id} ({len(job.get('stock_ids', []))} labels, {copies} copies)"
        )

        # Claim the job
        claimed = self.claim_job(job_id)
        if not claimed:
            return False

        # Try to get PNG image first (works better with Dymo printers)
        image_result = self.get_job_image(job_id)
        use_png = image_result is not None

        if use_png:
            image_data, content_type = image_result
            logger.debug(f"Got image data, content-type: {content_type}")
        else:
            # Fall back to PDF
            logger.debug("PNG not available, falling back to PDF")
            image_data = self.get_job_pdf(job_id)
            if not image_data:
                self.complete_job(
                    job_id, success=False, error_message="Failed to download label data"
                )
                return False

        # Mark as printing
        self.start_job(job_id)

        # Print using appropriate method
        try:
            if use_png:
                # Use PNG printing for Dymo (avoids CUPS PDF scaling issues)
                success = self.printer.print_png(
                    image_data,
                    title=f"FlyPush Labels - Job {job_id[:8]}",
                    copies=copies,
                    page_size="w72h154",  # Dymo 11352
                    dpi=300,
                )
            else:
                # Use PDF printing
                success = self.printer.print_pdf(
                    image_data,
                    title=f"FlyPush Labels - Job {job_id[:8]}",
                    copies=copies,
                    orientation=self.config.orientation,
                )

            if success:
                self.complete_job(job_id, success=True)
                logger.info(f"Job {job_id} printed successfully")
                return True
            else:
                self.complete_job(job_id, success=False, error_message="Print returned false")
                return False
        except PrinterError as e:
            error_msg = str(e)
            logger.error(f"Print error for job {job_id}: {error_msg}")
            self.complete_job(job_id, success=False, error_message=error_msg)
            return False

    def run_once(self) -> int:
        """Run a single polling cycle.

        Returns:
            int: Number of jobs processed.
        """
        # Send heartbeat
        self.send_heartbeat()

        # Get pending jobs
        jobs = self.get_pending_jobs()
        if not jobs:
            return 0

        # Process jobs
        processed = 0
        for job in jobs:
            if not self.running:
                break
            if self.process_job(job):
                processed += 1

        return processed

    def run(self) -> None:
        """Run the agent polling loop.

        Runs until interrupted or self.running is set to False.
        """
        if not self.config.is_configured():
            logger.error("Agent not configured. Run 'flyprint configure' first.")
            sys.exit(1)

        if not self.printer.is_available:
            logger.error("No printer available. Is CUPS installed and running?")
            sys.exit(1)

        logger.info("Starting FlyPrint agent")
        logger.info(f"Server: {self.config.server_url}")
        logger.info(f"Printer: {self.config.printer_name or 'default'}")
        logger.info(f"Poll interval: {self.config.poll_interval}s")

        self.running = True

        while self.running:
            try:
                self.run_once()
            except Exception as e:
                logger.exception(f"Error in agent loop: {e}")

            # Sleep until next poll
            time.sleep(self.config.poll_interval)

        logger.info("Agent stopped")

    def test_connection(self) -> dict:
        """Test connection to server and printer.

        Returns:
            dict: Test results with 'server', 'printer', 'success' keys.
        """
        results = {
            "server": {"status": "unknown", "message": ""},
            "printer": {"status": "unknown", "message": ""},
            "success": False,
        }

        # Test server connection
        try:
            if self.send_heartbeat():
                results["server"] = {"status": "ok", "message": "Connected to server"}
            else:
                results["server"] = {"status": "error", "message": "Server rejected heartbeat"}
        except Exception as e:
            results["server"] = {"status": "error", "message": str(e)}

        # Test printer
        if self.printer.is_available:
            printers = self.printer.get_printers()
            if printers:
                status = self.printer.get_printer_status()
                results["printer"] = {
                    "status": "ok",
                    "message": f"Printer status: {status}",
                    "printers": [p["name"] for p in printers],
                }
            else:
                results["printer"] = {"status": "warning", "message": "No printers found"}
        else:
            results["printer"] = {"status": "error", "message": "CUPS not available"}

        results["success"] = results["server"]["status"] == "ok" and results["printer"][
            "status"
        ] in ("ok", "warning")

        return results


def get_agent(config: FlyPrintConfig | None = None) -> FlyPrintAgent:
    """Factory function for FlyPrintAgent.

    Args:
        config: Optional configuration.

    Returns:
        FlyPrintAgent: Agent instance.
    """
    return FlyPrintAgent(config)
