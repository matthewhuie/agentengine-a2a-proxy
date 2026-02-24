import os

import httpx
from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

from .auth import BedrockAgentCoreAuth

A2A_AGENT_URL = os.getenv("A2A_AGENT_URL")
AWS_ROLE_ARN = os.getenv("AWS_ROLE_ARN")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_SERVICE = os.getenv("AWS_SERVICE", "bedrock")
# Path to the GCP service account JSON key file. When unset, Application
# Default Credentials are used (e.g. on a GCP VM with a service account).
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

if not A2A_AGENT_URL:
    raise ValueError(
        "Environment variable 'A2A_AGENT_URL' is required but was not set."
    )
if not AWS_ROLE_ARN:
    raise ValueError(
        "Environment variable 'AWS_ROLE_ARN' is required but was not set."
    )

auth = BedrockAgentCoreAuth(
    aws_role_arn=AWS_ROLE_ARN,
    aws_region=AWS_REGION,
    aws_service=AWS_SERVICE,
    service_account_file=GOOGLE_APPLICATION_CREDENTIALS or None,
)

http_client = httpx.AsyncClient(
    auth=auth,
    verify=True,
)

root_agent = RemoteA2aAgent(
    name="proxy_agent",
    description="Agent that proxies requests to an agent on AWS Bedrock AgentCore.",
    agent_card=f"{A2A_AGENT_URL}{AGENT_CARD_WELL_KNOWN_PATH}",
    httpx_client=http_client,
)
