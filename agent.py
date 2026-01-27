from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

root_agent = RemoteA2aAgent(
    name="proxy_agent",
    description="Agent that proxies requests to an agent on an A2A server.",
    agent_card="https://A2A_AGENT_URL{AGENT_CARD_WELL_KNOWN_PATH}",
)
