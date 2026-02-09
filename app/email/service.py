"""Email service for sending notifications."""

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import get_settings

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails via SMTP.

    Attributes:
        settings: Application settings containing SMTP configuration.
    """

    def __init__(self):
        """Initialize the email service with settings."""
        self.settings = get_settings()

    @property
    def app_name(self) -> str:
        """Get the application name from settings."""
        return self.settings.app_name

    def _create_smtp_connection(self) -> smtplib.SMTP_SSL | smtplib.SMTP:
        """Create an SMTP connection based on settings.

        Returns:
            SMTP connection object.

        Raises:
            smtplib.SMTPException: If connection fails.
        """
        if self.settings.smtp_use_tls:
            # Use SSL/TLS from the start (port 465)
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(
                self.settings.smtp_host,
                self.settings.smtp_port,
                context=context,
            )
        else:
            # Use STARTTLS (port 587)
            server = smtplib.SMTP(
                self.settings.smtp_host,
                self.settings.smtp_port,
            )
            server.starttls()

        # Login if credentials provided
        if self.settings.smtp_user and self.settings.smtp_password:
            server.login(self.settings.smtp_user, self.settings.smtp_password)

        return server

    def send_email(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: str | None = None,
    ) -> bool:
        """Send an email.

        Args:
            to_email: Recipient email address.
            subject: Email subject.
            body_html: HTML body content.
            body_text: Plain text body (optional, generated from HTML if not provided).

        Returns:
            bool: True if email sent successfully, False otherwise.
        """
        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{self.settings.smtp_from_name} <{self.settings.smtp_from_email}>"
            msg["To"] = to_email

            # Add plain text version
            if body_text is None:
                # Simple HTML to text conversion
                import re

                body_text = re.sub(r"<[^>]+>", "", body_html)
                body_text = re.sub(r"\s+", " ", body_text).strip()

            msg.attach(MIMEText(body_text, "plain"))
            msg.attach(MIMEText(body_html, "html"))

            # Send email
            with self._create_smtp_connection() as server:
                server.sendmail(
                    self.settings.smtp_from_email,
                    to_email,
                    msg.as_string(),
                )

            logger.info(f"Email sent successfully to {to_email}: {subject}")
            return True

        except smtplib.SMTPException as e:
            logger.error(f"SMTP error sending email to {to_email}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending email to {to_email}: {e}")
            return False

    def send_welcome_email(self, to_email: str, full_name: str, is_approved: bool = True) -> bool:
        """Send a welcome email to a new user.

        Args:
            to_email: User's email address.
            full_name: User's full name.
            is_approved: Whether the user is approved or pending.

        Returns:
            bool: True if sent successfully.
        """
        if is_approved:
            subject = f"Welcome to {self.app_name}!"
            body_html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <h2>Welcome to {self.app_name}, {full_name}!</h2>
                <p>Your account has been created and you're ready to start managing your fly stocks.</p>
                <p>You can now log in and:</p>
                <ul>
                    <li>Add and manage your fly stocks</li>
                    <li>Plan and track crosses</li>
                    <li>Generate labels for your vials</li>
                    <li>Import stocks from CSV files</li>
                </ul>
                <p>If you have any questions, please contact your lab administrator.</p>
                <p>Best regards,<br>The {self.app_name} Team</p>
            </body>
            </html>
            """
        else:
            subject = f"{self.app_name} Registration - Pending Approval"
            body_html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <h2>Thank you for registering, {full_name}!</h2>
                <p>Your {self.app_name} account has been created and is pending approval from your lab's PI.</p>
                <p>You will receive another email once your account has been approved.</p>
                <p>If you have any questions, please contact your lab administrator.</p>
                <p>Best regards,<br>The {self.app_name} Team</p>
            </body>
            </html>
            """

        return self.send_email(to_email, subject, body_html)

    def send_approval_email(self, to_email: str, full_name: str) -> bool:
        """Send an email notifying user their account was approved.

        Args:
            to_email: User's email address.
            full_name: User's full name.

        Returns:
            bool: True if sent successfully.
        """
        subject = f"{self.app_name} Account Approved!"
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2>Good news, {full_name}!</h2>
            <p>Your {self.app_name} account has been approved. You can now log in and start using the application.</p>
            <p>Best regards,<br>The {self.app_name} Team</p>
        </body>
        </html>
        """
        return self.send_email(to_email, subject, body_html)

    def send_rejection_email(self, to_email: str, full_name: str) -> bool:
        """Send an email notifying user their account was rejected.

        Args:
            to_email: User's email address.
            full_name: User's full name.

        Returns:
            bool: True if sent successfully.
        """
        subject = f"{self.app_name} Registration Update"
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2>Hello {full_name},</h2>
            <p>Unfortunately, your {self.app_name} registration request was not approved.</p>
            <p>If you believe this was a mistake, please contact the lab administrator directly.</p>
            <p>Best regards,<br>The {self.app_name} Team</p>
        </body>
        </html>
        """
        return self.send_email(to_email, subject, body_html)

    def send_password_reset_email(
        self,
        to_email: str,
        full_name: str,
        reset_url: str,
    ) -> bool:
        """Send password reset email with reset link.

        Args:
            to_email: User's email address.
            full_name: User's full name.
            reset_url: Full URL to reset password page with token.

        Returns:
            bool: True if sent successfully.
        """
        subject = f"{self.app_name} - Password Reset Request"
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2>Password Reset Request</h2>
            <p>Hello {full_name},</p>
            <p>We received a request to reset your {self.app_name} password. Click the link below to set a new password:</p>
            <p style="margin: 20px 0;">
                <a href="{reset_url}" style="background-color: #4F46E5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">
                    Reset Password
                </a>
            </p>
            <p>Or copy and paste this link into your browser:</p>
            <p style="word-break: break-all; color: #4F46E5;">{reset_url}</p>
            <p><strong>This link will expire in 1 hour.</strong></p>
            <p>If you didn't request a password reset, you can safely ignore this email. Your password will remain unchanged.</p>
            <p>Best regards,<br>The {self.app_name} Team</p>
        </body>
        </html>
        """
        return self.send_email(to_email, subject, body_html)

    def send_verification_email(
        self,
        to_email: str,
        full_name: str,
        verification_url: str,
    ) -> bool:
        """Send email verification link to new user.

        Args:
            to_email: User's email address.
            full_name: User's full name.
            verification_url: Full URL to verify email with token.

        Returns:
            bool: True if sent successfully.
        """
        subject = f"{self.app_name} - Please Verify Your Email"
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2>Welcome to {self.app_name}, {full_name}!</h2>
            <p>Thank you for registering. Please verify your email address by clicking the button below:</p>
            <p style="margin: 20px 0;">
                <a href="{verification_url}" style="background-color: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">
                    Verify Email Address
                </a>
            </p>
            <p>Or copy and paste this link into your browser:</p>
            <p style="word-break: break-all; color: #2563eb;">{verification_url}</p>
            <p><strong>This link will expire in 24 hours.</strong></p>
            <p>If you didn't create an account on {self.app_name}, you can safely ignore this email.</p>
            <p>Best regards,<br>The {self.app_name} Team</p>
        </body>
        </html>
        """
        return self.send_email(to_email, subject, body_html)

    def send_new_member_notification(
        self,
        admin_email: str,
        admin_name: str,
        new_user_name: str,
        new_user_email: str,
    ) -> bool:
        """Send notification to admin about a new member requesting access.

        Args:
            admin_email: Admin's email address.
            admin_name: Admin's full name.
            new_user_name: New user's full name.
            new_user_email: New user's email.

        Returns:
            bool: True if sent successfully.
        """
        subject = f"{self.app_name}: New Member Request from {new_user_name}"
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2>Hello {admin_name},</h2>
            <p>A new user has requested to join your lab on {self.app_name}:</p>
            <ul>
                <li><strong>Name:</strong> {new_user_name}</li>
                <li><strong>Email:</strong> {new_user_email}</li>
            </ul>
            <p>Please log in to the Admin Panel to approve or reject this request.</p>
            <p>Best regards,<br>The {self.app_name} Team</p>
        </body>
        </html>
        """
        return self.send_email(admin_email, subject, body_html)

    def send_invitation_email(
        self,
        to_email: str,
        invitation_type: str,
        inviter_name: str,
        tenant_name: str,
        organization_name: str | None,
        registration_url: str,
        expires_days: int = 7,
    ) -> bool:
        """Send an invitation email to a prospective user.

        Args:
            to_email: Invitee's email address.
            invitation_type: "lab_member" or "new_tenant".
            inviter_name: Name of the person sending the invitation.
            tenant_name: Lab name.
            organization_name: Organization name (for new_tenant type).
            registration_url: Full URL to registration page with token.
            expires_days: Number of days until invitation expires.

        Returns:
            bool: True if sent successfully.
        """
        if invitation_type == "new_tenant":
            subject = f"{self.app_name} - You're invited to create a new lab in {organization_name}"
            heading = "You've been invited to create a new lab"
            description = (
                f"{inviter_name} from <strong>{tenant_name}</strong> has invited you to create "
                f"a new lab within <strong>{organization_name}</strong> on {self.app_name}."
            )
        else:
            subject = f"{self.app_name} - You're invited to join {tenant_name}"
            heading = f"You've been invited to join {tenant_name}"
            description = (
                f"{inviter_name} has invited you to join <strong>{tenant_name}</strong> "
                f"on {self.app_name}."
            )

        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2>{heading}</h2>
            <p>{description}</p>
            <p>Click the button below to create your account:</p>
            <p style="margin: 20px 0;">
                <a href="{registration_url}" style="background-color: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">
                    Accept Invitation
                </a>
            </p>
            <p>Or copy and paste this link into your browser:</p>
            <p style="word-break: break-all; color: #2563eb;">{registration_url}</p>
            <p><strong>This invitation expires in {expires_days} days.</strong></p>
            <p>If you weren't expecting this invitation, you can safely ignore this email.</p>
            <p>Best regards,<br>The {self.app_name} Team</p>
        </body>
        </html>
        """
        return self.send_email(to_email, subject, body_html)

    def send_flip_reminder_email(
        self,
        to_email: str,
        user_name: str,
        stocks: list,
        tenant_name: str,
    ) -> bool:
        """Send weekly flip reminder email with stocks needing attention.

        Args:
            to_email: Recipient email address.
            user_name: Recipient's name.
            stocks: List of StockFlipInfo objects needing attention.
            tenant_name: Lab/tenant name.

        Returns:
            bool: True if sent successfully.
        """
        # Separate critical and warning stocks
        critical_stocks = [s for s in stocks if s.flip_status.value == "critical"]
        warning_stocks = [s for s in stocks if s.flip_status.value == "warning"]

        # Build stock table HTML
        def build_stock_row(stock, is_critical: bool) -> str:
            status_color = "#dc2626" if is_critical else "#f59e0b"
            status_text = "CRITICAL" if is_critical else "Warning"
            days_text = (
                f"{stock.days_since_flip} days ago"
                if stock.days_since_flip is not None
                else "Never"
            )
            return f"""
            <tr style="border-bottom: 1px solid #e5e7eb;">
                <td style="padding: 12px 8px; color: {status_color}; font-weight: 600;">
                    {status_text}
                </td>
                <td style="padding: 12px 8px; font-weight: 500;">
                    {stock.stock_display_id}
                </td>
                <td style="padding: 12px 8px;">
                    {days_text}
                </td>
            </tr>
            """

        stock_rows = ""
        for stock in critical_stocks:
            stock_rows += build_stock_row(stock, is_critical=True)
        for stock in warning_stocks:
            stock_rows += build_stock_row(stock, is_critical=False)

        subject = f"{self.app_name}: {len(stocks)} stock(s) need flipping"
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2>Hello {user_name},</h2>
            <p>This is your weekly reminder from {self.app_name} about stocks in <strong>{tenant_name}</strong> that need to be flipped to fresh food.</p>

            <div style="margin: 24px 0; padding: 16px; background-color: #fef2f2; border-radius: 8px; border-left: 4px solid #dc2626;">
                <p style="margin: 0; color: #991b1b;">
                    <strong>{len(critical_stocks)} stock(s)</strong> are past the critical threshold and need immediate attention.
                </p>
            </div>

            <div style="margin: 24px 0; padding: 16px; background-color: #fffbeb; border-radius: 8px; border-left: 4px solid #f59e0b;">
                <p style="margin: 0; color: #92400e;">
                    <strong>{len(warning_stocks)} stock(s)</strong> are approaching the critical threshold.
                </p>
            </div>

            <table style="width: 100%; border-collapse: collapse; margin: 24px 0;">
                <thead>
                    <tr style="background-color: #f9fafb; border-bottom: 2px solid #e5e7eb;">
                        <th style="padding: 12px 8px; text-align: left; font-weight: 600;">Status</th>
                        <th style="padding: 12px 8px; text-align: left; font-weight: 600;">Stock ID</th>
                        <th style="padding: 12px 8px; text-align: left; font-weight: 600;">Last Flipped</th>
                    </tr>
                </thead>
                <tbody>
                    {stock_rows}
                </tbody>
            </table>

            <p>Please log in to {self.app_name} to flip these stocks and print new labels.</p>

            <p style="color: #6b7280; font-size: 14px; margin-top: 32px;">
                You can adjust flip reminder settings or disable these emails in the Settings page.
            </p>

            <p>Best regards,<br>The {self.app_name} Team</p>
        </body>
        </html>
        """
        return self.send_email(to_email, subject, body_html)


# Singleton instance
_email_service: EmailService | None = None


def get_email_service() -> EmailService:
    """Get the email service singleton.

    Returns:
        EmailService: The email service instance.
    """
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
