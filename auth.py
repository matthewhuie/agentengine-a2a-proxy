"""Authentication for AWS Bedrock AgentCore using a GCP service account.

Auth chain:
  GCP Service Account
    -> OIDC ID token  (audience: https://sts.amazonaws.com)
    -> AWS STS AssumeRoleWithWebIdentity
    -> Temporary AWS credentials
    -> AWS SigV4-signed requests to Bedrock AgentCore
"""

import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

import boto3
import botocore.auth
import botocore.awsrequest
import botocore.credentials
import httpx


class BedrockAgentCoreAuth(httpx.AsyncAuth):
    """httpx AsyncAuth that signs requests to AWS Bedrock AgentCore.

    On each request:
      1. Obtains a GCP service account OIDC ID token (audience: AWS STS).
      2. Calls STS AssumeRoleWithWebIdentity to get temporary AWS credentials.
      3. Signs the request with AWS Signature Version 4.

    Temporary credentials are cached and refreshed automatically 5 minutes
    before expiry to avoid clock-skew issues.
    """

    # Tell httpx to buffer the request body before calling auth_flow,
    # so request.content is always available for body hashing.
    requires_request_body = True

    # Refresh credentials this many seconds before they actually expire.
    _EXPIRY_BUFFER_SECONDS = 300

    def __init__(
        self,
        aws_role_arn: str,
        aws_region: str,
        service_account_file: Optional[str] = None,
        aws_service: str = "bedrock",
        session_name: str = "gcp-agentcore-session",
    ) -> None:
        """
        Args:
            aws_role_arn: ARN of the AWS IAM role to assume via web identity
                federation. Example:
                ``arn:aws:iam::123456789012:role/GCPBedrockAgentCoreRole``
            aws_region: AWS region where Bedrock AgentCore is deployed.
                Example: ``us-east-1``
            service_account_file: Path to a GCP service account JSON key file.
                When ``None``, Application Default Credentials (ADC) are used
                instead. ADC must resolve to a credential type that supports
                OIDC ID tokens (e.g. a service account key, or a Workload
                Identity configuration).
            aws_service: AWS service name used for SigV4 signing. Defaults to
                ``"bedrock"``; override if AgentCore uses a different signing
                name (e.g. ``"bedrock-agentcore"``).
            session_name: Identifier tag attached to the assumed-role session,
                visible in AWS CloudTrail logs.
        """
        self._aws_role_arn = aws_role_arn
        self._aws_region = aws_region
        self._service_account_file = service_account_file
        self._aws_service = aws_service
        self._session_name = session_name
        self._cached_credentials: Optional[dict] = None
        self._credentials_expiry: Optional[datetime] = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Credential acquisition (synchronous — run in a thread pool)
    # ------------------------------------------------------------------

    def _get_gcp_oidc_token(self) -> str:
        """Return a fresh GCP OIDC ID token targeted at AWS STS.

        AWS STS uses the token's ``aud`` claim to verify the issuer, so the
        audience must be ``https://sts.amazonaws.com``.
        """
        import google.auth
        import google.auth.transport.requests
        import google.oauth2.service_account

        audience = "https://sts.amazonaws.com"

        if self._service_account_file:
            creds = google.oauth2.service_account.IDTokenCredentials.from_service_account_file(
                self._service_account_file,
                target_audience=audience,
            )
        else:
            creds, _ = google.auth.default()
            if not hasattr(creds, "with_target_audience"):
                raise RuntimeError(
                    "Application Default Credentials do not support OIDC ID "
                    "tokens. Set GOOGLE_APPLICATION_CREDENTIALS to a service "
                    "account JSON key file, or use a Workload Identity "
                    "configuration."
                )
            creds = creds.with_target_audience(audience)

        creds.refresh(google.auth.transport.requests.Request())
        return creds.token

    def _sync_fetch_aws_credentials(self) -> dict:
        """Exchange the GCP OIDC token for temporary AWS credentials via STS."""
        oidc_token = self._get_gcp_oidc_token()
        sts = boto3.client("sts", region_name=self._aws_region)
        response = sts.assume_role_with_web_identity(
            RoleArn=self._aws_role_arn,
            RoleSessionName=self._session_name,
            WebIdentityToken=oidc_token,
        )
        return response["Credentials"]

    # ------------------------------------------------------------------
    # Async credential management
    # ------------------------------------------------------------------

    async def _get_aws_credentials(self) -> dict:
        """Return valid AWS credentials, refreshing transparently when near expiry."""
        now = datetime.now(timezone.utc)
        needs_refresh = (
            self._cached_credentials is None
            or self._credentials_expiry is None
            or (self._credentials_expiry - now).total_seconds()
            < self._EXPIRY_BUFFER_SECONDS
        )

        if needs_refresh:
            async with self._lock:
                # Re-evaluate after acquiring the lock (double-checked locking).
                now = datetime.now(timezone.utc)
                if (
                    self._cached_credentials is None
                    or self._credentials_expiry is None
                    or (self._credentials_expiry - now).total_seconds()
                    < self._EXPIRY_BUFFER_SECONDS
                ):
                    creds = await asyncio.to_thread(self._sync_fetch_aws_credentials)
                    self._cached_credentials = creds
                    self._credentials_expiry = creds["Expiration"]

        return self._cached_credentials

    # ------------------------------------------------------------------
    # httpx auth flow
    # ------------------------------------------------------------------

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """Sign *request* with AWS SigV4 before it is sent."""
        credentials = await self._get_aws_credentials()

        boto_creds = botocore.credentials.Credentials(
            access_key=credentials["AccessKeyId"],
            secret_key=credentials["SecretAccessKey"],
            token=credentials["SessionToken"],
        )

        # Build a botocore AWSRequest so we can use its SigV4 implementation.
        aws_request = botocore.awsrequest.AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers=dict(request.headers),
        )

        signer = botocore.auth.SigV4Auth(
            boto_creds, self._aws_service, self._aws_region
        )
        signer.add_auth(aws_request)

        # Copy the signed headers (Authorization, X-Amz-Date, X-Amz-Security-Token,
        # X-Amz-Content-SHA256) back onto the httpx request.
        for header, value in aws_request.headers.items():
            request.headers[header] = value

        yield request
