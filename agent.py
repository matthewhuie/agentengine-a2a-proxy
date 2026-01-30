import os
import httpx
from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

AUTH_TOKEN = os.getenv("AUTH_TOKEN") 
A2A_AGENT_URL = os.getenv("A2A_AGENT_URL")

if not A2A_AGENT_URL:
    raise ValueError("Environment variable 'A2A_AGENT_URL' is required but was not found.")

headers = {}
if AUTH_TOKEN:
    headers["Authorization"] = f"Bearer {AUTH_TOKEN}"

http_client = httpx.AsyncClient(
    headers=headers,
    verify=True 
)

root_agent = RemoteA2aAgent(
    name="proxy_agent",
    description="Agent that proxies requests to an agent on an A2A server.",
    agent_card=f"{A2A_AGENT_URL}{AGENT_CARD_WELL_KNOWN_PATH}",
    httpx_client=http_client,
)
