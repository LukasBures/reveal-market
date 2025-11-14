from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from shared.logging import log_event

from .config import get_settings
from .summary_jobs import SummaryJob

logger = logging.getLogger("reveal_market.worker.summary_client")


class SummaryClientError(Exception):
    """Raised when the AI provider cannot produce a summary."""


@dataclass
class SummaryResult:
    text: str
    model: str
    source: str
    metadata: dict[str, Any]
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class SummaryClient:
    """Client responsible for producing AI summaries via OpenAI (or fallback)."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = get_settings()
        self._transport = transport
        api_key = self.settings.summary_api_key.get_secret_value() if self.settings.summary_api_key else None
        self._api_key = api_key

    def generate(self, job: SummaryJob) -> SummaryResult:
        prompt = self._render_prompt(job)
        if self._api_key:
            try:
                log_event(
                    logger,
                    logging.DEBUG,
                    event="worker.summary.provider_dispatch",
                    message="sending prompt to summary provider",
                    job_id=job.job_id,
                    event_id=job.event_id,
                )
                return self._call_openai(prompt)
            except Exception as exc:  # pragma: no cover - network paths
                logger.warning(
                    "summary provider call failed: %s", exc, extra={"event": "worker.summary.provider_error"}
                )
                if not self.settings.summary_fallback_enabled:
                    raise SummaryClientError(str(exc)) from exc
        if not self.settings.summary_fallback_enabled:
            raise SummaryClientError("summary provider disabled and fallback not allowed")
        log_event(
            logger,
            logging.INFO,
            event="worker.summary.fallback",
            message="using fallback summary generator",
            job_id=job.job_id,
            event_id=job.event_id,
            reason="provider_unavailable" if self._api_key else "api_key_missing",
        )
        text = self._fallback_summary(job, prompt_hint=prompt)
        metadata = {
            "mode": "fallback",
            "reason": "provider_unavailable" if self._api_key else "api_key_missing",
            "requested_at": job.requested_at.isoformat(),
        }
        return SummaryResult(
            text=text,
            model="fallback-generator",
            source=self.settings.summary_source_label,
            metadata=metadata,
            generated_at=datetime.now(UTC),
        )

    def _render_prompt(self, job: SummaryJob) -> str:
        template = self.settings.summary_prompt_template
        description = job.description.strip()
        extra_context = job.metadata.get("extra_data") or job.metadata
        tags = ", ".join(job.tags) if job.tags else "none"
        return template.format(
            title=job.title,
            category=job.category or "general",
            tags=tags,
            description=description,
            extra_context=extra_context,
            min_words=self.settings.summary_min_words,
            max_words=self.settings.summary_max_words,
        )

    def _call_openai(self, prompt: str) -> SummaryResult:
        base_url = str(self.settings.summary_api_base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/chat/completions"
        payload = {
            "model": self.settings.summary_model,
            "temperature": 0.4,
            "max_tokens": 800,
            "presence_penalty": 0.2,
            "frequency_penalty": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a research assistant for a prediction market venue. "
                        "Write fact-focused briefs using only public knowledge. "
                        "Always cite uncertainties and avoid speculation."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self.settings.summary_http_timeout_seconds)
        with httpx.Client(timeout=timeout, transport=self._transport) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
        choices = body.get("choices") or []
        if not choices:
            raise SummaryClientError("provider returned no choices")
        content = choices[0].get("message", {}).get("content") or ""
        cleaned = content.strip()
        if not cleaned:
            raise SummaryClientError("provider returned empty content")
        metadata = {
            "provider": "openai",
            "model": self.settings.summary_model,
            "usage": body.get("usage"),
        }
        log_event(
            logger,
            logging.INFO,
            event="worker.summary.provider_success",
            message="summary provider returned content",
            model=self.settings.summary_model,
        )
        return SummaryResult(
            text=cleaned,
            model=self.settings.summary_model,
            source=self.settings.summary_source_label,
            metadata=metadata,
            generated_at=datetime.now(UTC),
        )

    def _fallback_summary(self, job: SummaryJob, *, prompt_hint: str) -> str:
        min_words = self.settings.summary_min_words
        max_words = self.settings.summary_max_words
        base_sentences = [
            f"{job.title.strip()} is currently listed under the {job.category or 'general'} category on Reveal Market.",
            "This interim write-up was generated automatically while the AI enrichment pipeline is warming up.",
            "Investors should validate every figure against trusted public sources before relying on this summary.",
        ]
        description_words = _tokenize(job.description)
        prompt_words = _tokenize(prompt_hint)
        combined: list[str] = []
        for sentence in base_sentences:
            combined.extend(_tokenize(sentence))
        while len(combined) < min_words:
            combined.extend(description_words or prompt_words or base_sentences[0].split())
        clipped = combined[: min(max_words, len(combined))]
        text = " ".join(clipped)
        text = _normalize_spacing(text)
        log_event(
            logger,
            logging.DEBUG,
            event="worker.summary.fallback_generated",
            message="fallback summary generated",
            job_id=job.job_id,
            token_count=len(text.split()),
        )
        return text


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9']+|[.,;:]", text or "", re.MULTILINE)
    return tokens


def _normalize_spacing(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    return text.strip()
