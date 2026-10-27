"""AzureFoundryService: runs the agents on the GPT deployment of an Azure AI Foundry resource with the Microsoft
Agent Framework (structured answers, a picture when the agent needs to see the moment) and asks Microsoft
Decision-1 for its choice. Both are reached with the resource's endpoint, the deployment name and an API key
(no az login). Which agent, its instructions and its input come from logic/; this class only provides the
models. ready / decision1_ready say whether the .env names them; without them logic/ uses its local stand-ins."""
from __future__ import annotations

import asyncio

import httpx
from agent_framework import Agent, Content, Message
from agent_framework.openai import OpenAIChatClient

from src.core.settings import settings
from src.core.utils import (
    LIGHT_AGENTS,
    choice_probabilities,
    decision1_url,
    foundry_root,
)


class AzureFoundryService:
    def __init__(self):
        self._clients = {}
        self._lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        return settings.foundry_ready

    @property
    def decision1_ready(self) -> bool:
        return settings.decision1_ready

    def model_for(self, name: str) -> str:
        """The GPT deployment an agent runs on: the light one for the agents that only write text from finished
        results (LIGHT_AGENTS), when FOUNDRY_LIGHT_MODEL names it; FOUNDRY_MODEL for every other agent."""
        if name in LIGHT_AGENTS and settings.foundry_light_model:
            return settings.foundry_light_model
        return settings.foundry_model

    async def client(self, model: str):
        """One chat client per deployment, made on its first call: the Foundry resource's endpoint, the GPT
        deployment as the model and the resource key (Azure routing of the Agent Framework's OpenAI client)."""
        async with self._lock:
            if model not in self._clients:
                self._clients[model] = OpenAIChatClient(model=model, api_key=settings.foundry_api_key,
                                                        azure_endpoint=foundry_root(settings.foundry_endpoint))
        return self._clients[model]

    async def run(self, name: str, instructions: str, text: str, shape, image: bytes | None = None):
        """One agent answer in the shape of a Pydantic model. image: a PNG the agent looks at with the text.
        A model that hangs fails the call after AGENT_TIMEOUT_S."""
        if not self.ready:
            raise RuntimeError("Foundry is not set up (FOUNDRY_ENDPOINT, FOUNDRY_MODEL, FOUNDRY_API_KEY)")
        ask = Message("user", [Content.from_text(text), Content.from_data(image, "image/png")]) if image else text
        async with Agent(await self.client(self.model_for(name)), instructions, name=name) as agent:
            resp = await asyncio.wait_for(agent.run(ask, options={"response_format": shape}),
                                          settings.agent_timeout_s)
        return resp.value if resp.value is not None else shape.model_validate_json(resp.text)

    async def decision1(self, body: dict) -> dict[str, float]:
        """Decision-1 (Foundry's systemone API, text only) -> a probability for each labelled option of the
        "decision" question. The key goes in the api-key header."""
        if not self.decision1_ready:
            raise RuntimeError("Decision-1 is not set up (DECISION1_ENDPOINT, DECISION1_DEPLOYMENT, DECISION1_API_KEY)")
        headers = {"api-key": settings.decision1_api_key}
        url = decision1_url(settings.decision1_endpoint)
        async with httpx.AsyncClient(timeout=settings.agent_timeout_s) as http:
            r = await http.post(url, json=body, headers=headers)
        if r.is_error:   # Azure's answer says why (wrong address, key, deployment or body); it holds no key
            raise RuntimeError(f"HTTP {r.status_code} from {url}: {r.text[:400]}")
        return choice_probabilities(r.json()["answers"]["decision"])

    async def close(self):
        """Nothing to sign out of; kept so main.py's shutdown stays the same."""
        self._clients = {}


foundry = AzureFoundryService()
