"""Constrained OpenAI-compatible LLM gateway with opt-in cloud fallback.

Model endpoints are trusted *configuration*, never supplied by end users or model
responses. API tokens are not logged or returned to the dashboard.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from mio.config import Settings


class ModelUnavailable(RuntimeError):
    """No permitted model returned a usable answer."""


@dataclass(frozen=True)
class Completion:
    text: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def validate_provider_url(url: str, *, local: bool) -> str:
    """Allow only loopback for local inference, HTTPS for cloud inference."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Model endpoint must not contain credentials/query/fragment")
    if local:
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError("Local model URL must point to a loopback IP")
        except ValueError as exc:
            if host != "localhost":
                raise ValueError("Local model URL must point to loopback") from exc
        if parts.scheme != "http":
            raise ValueError("Local model URL must use http on loopback")
    elif parts.scheme != "https" or not host:
        raise ValueError("Cloud model URL must use HTTPS")
    if parts.path.rstrip("/") not in ("/v1", ""):
        raise ValueError("Base model URL path must be /v1 or empty")
    return url.rstrip("/")


class ModelRouter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def configured(self) -> bool:
        return bool(self.settings.mio_local_model or (
            self.settings.mio_allow_cloud and self.settings.mio_cloud_model
            and self.settings.mio_cloud_api_key
        ))

    def providers(self) -> list[tuple[str, str, str, str]]:
        candidates: list[tuple[str, str, str, str]] = []
        if self.settings.mio_local_model:
            url = validate_provider_url(self.settings.mio_local_base_url, local=True)
            candidates.append(("local", url, self.settings.mio_local_model, "ollama"))
        if (self.settings.mio_allow_cloud and self.settings.mio_cloud_model
                and self.settings.mio_cloud_api_key):
            url = validate_provider_url(self.settings.mio_cloud_base_url, local=False)
            candidates.append(("cloud", url, self.settings.mio_cloud_model,
                               self.settings.mio_cloud_api_key.get_secret_value()))
        if self.settings.mio_model_route == "cloud":
            candidates.reverse()
        if self.settings.mio_model_route == "local":
            candidates = [item for item in candidates if item[0] == "local"]
        return candidates

    async def complete(self, messages: list[dict[str, str]], max_tokens: int = 768) -> Completion:
        if not self.configured():
            raise ModelUnavailable("No model configured. Set MIO_LOCAL_MODEL for local inference.")
        failures = []
        for kind, base, model, key in self.providers():
            try:
                # No ambient HTTP proxies or credentials; endpoints come from admin settings.
                # Project drafting produces significantly more tokens than a short
                # chat turn. Give that one operation enough inference time without
                # holding every small chat request for four minutes.
                deadline = 270.0 if max_tokens > 2048 else (240.0 if max_tokens >= 2048 else 120.0)
                async with httpx.AsyncClient(timeout=httpx.Timeout(deadline, connect=6.0),
                                             follow_redirects=False, trust_env=False) as client:
                    reply = await client.post(
                        f"{base}/chat/completions",
                        headers={"Authorization": f"Bearer {key}"},
                        json={"model": model, "messages": messages,
                              "stream": False, "max_tokens": min(max_tokens, 3072),
                              "temperature": 0.2},
                    )
                    reply.raise_for_status()
                    payload = reply.json()
                choices = payload.get("choices") or []
                value = choices[0].get("message", {}).get("content") if choices else None
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("Model returned no text")
                usage = payload.get("usage") or {}
                return Completion(text=value.strip(), model=model, provider=kind,
                                  input_tokens=usage.get("prompt_tokens"),
                                  output_tokens=usage.get("completion_tokens"))
            except httpx.HTTPStatusError as exc:
                # HTTP status is safe telemetry; upstream bodies and headers may
                # contain private prompts or service credentials. Never log them.
                failures.append(f"{kind} model HTTP {exc.response.status_code}")
            except httpx.TimeoutException:
                failures.append(f"{kind} model timed out")
            except httpx.HTTPError as exc:
                failures.append(f"{kind} model transport {type(exc).__name__}")
            except (ValueError, KeyError, IndexError) as exc:
                failures.append(f"{kind} model invalid response ({type(exc).__name__})")
        raise ModelUnavailable("; ".join(failures) or "No permitted provider available")

    async def probe(self) -> dict:
        """Non-secret configuration and reachability; no inference and no cloud calls."""
        result = {"configured": self.configured(),
                  "route": self.settings.mio_model_route,
                  "local_model": self.settings.mio_local_model or None,
                  "cloud_enabled": self.settings.mio_allow_cloud,
                  "cloud_model": self.settings.mio_cloud_model if self.settings.mio_allow_cloud else None,
                  "local_reachable": False}
        if not self.settings.mio_local_model:
            return result
        try:
            base = validate_provider_url(self.settings.mio_local_base_url, local=True)
            async with httpx.AsyncClient(timeout=2.0, trust_env=False,
                                         follow_redirects=False) as client:
                response = await client.get(f"{base}/models")
                result["local_reachable"] = response.status_code == 200
        except (httpx.HTTPError, ValueError):
            pass
        return result
