"""Candidate-only attribution boundary; native LiteLLM builds and delivers traces.

The pinned proxy strips caller user_api_key_* fields and stamps authenticated
key state before building StandardLoggingPayload (including proxy-only errors).
Only that owner field is trusted here. See docs/candidate/langfuse.md.
"""

import asyncio
import logging
import os
import re
import threading
from collections.abc import Mapping
from urllib.parse import quote
from uuid import uuid4

from litellm.integrations.custom_logger import CustomLogger
from litellm.integrations.langfuse.langfuse import LangFuseLogger
from pydantic import BaseModel

log = logging.getLogger(__name__)
_CREDENTIAL = (
    r"authorization|proxy[-_]authorization|(?:[\w-]+[-_])?api[-_]key|"
    r"(?:access|refresh|oauth|id)[-_]token|(?:x[-_])?(?:provider|management|client)[-_](?:key|secret)|"
    r"password|secret[-_]key|cookie|set[-_]cookie"
)
_KEY = re.compile(rf"^(?:{_CREDENTIAL})$", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    rf"(?P<label>\b(?:{_CREDENTIAL})\b[\"']?\s*[:=]\s*)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|(?:Bearer\s+|Basic\s+)?[^\s,;\}\]\"']+)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9_./+~=-]+", re.IGNORECASE)
_SECRET_ENV = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "CPA_API_KEY",
    "LITELLM_MASTER_KEY",
    "LITELLM_SALT_KEY",
    "UI_PASSWORD",
    "POSTGRES_PASSWORD",
)


def _mask_assignment(match):
    value = match["value"]
    delimiter = value[0] if value[0] in "\"'" else ""
    return match["label"] + delimiter + "[REDACTED]" + delimiter


def _masked(value, secrets):
    """Copy only, including native Pydantic response types required by the logger."""
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = _ASSIGNMENT.sub(_mask_assignment, value)
        return _BEARER.sub(r"\1 [REDACTED]", value)
    if isinstance(value, BaseModel):
        fields = {**value.__dict__, **(value.model_extra or {})}
        return value.model_copy(update=_masked(fields, secrets))
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]"
            if isinstance(key, str) and _KEY.fullmatch(key)
            else _masked(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_masked(item, secrets) for item in value]
    return value


class NativeLangfuse(CustomLogger):
    def __init__(self):
        super().__init__(turn_off_message_logging=False)
        self._native = None
        self._lock = threading.Lock()

    def _logger(self):
        with self._lock:
            if self._native is None:
                self._native = LangFuseLogger(
                    langfuse_public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
                    langfuse_secret=os.environ["LANGFUSE_SECRET_KEY"],
                    langfuse_host=os.environ["LANGFUSE_HOST"],
                    allow_env_credentials=False,
                )
            return self._native

    def _emit(self, kwargs, response_obj, start_time, end_time, failed=False):
        standard = kwargs.get("standard_logging_object") or {}
        trusted = standard.get("metadata") or {}
        owner = trusted.get("user_api_key_user_id")
        deployment = quote(os.environ["PROXYLENS_TRACE_DEPLOYMENT"], safe="")
        user = f"{deployment}/{quote(owner, safe='')}" if isinstance(owner, str) and owner else None
        nonce = uuid4().hex
        metadata = {
            "attribution_basis": "key_owner" if user else "unattributed",
            "session_basis": "request_fallback",
            "cost_basis": "estimated_api_equivalent",
        }
        local = {
            "model": kwargs.get("model"),
            "call_type": kwargs.get("call_type"),
            "messages": kwargs.get("messages"),
            "optional_params": kwargs.get("optional_params") or {},
            "response_cost": kwargs.get("response_cost"),
            "completion_start_time": kwargs.get("completion_start_time"),
            "custom_llm_provider": kwargs.get("custom_llm_provider"),
            "litellm_call_id": nonce,
            "litellm_params": {
                "metadata": {
                    "trace_id": nonce,
                    "trace_user_id": user,
                    "session_id": f"{user or deployment + '/unattributed'}/request/{nonce}",
                    "trace_public": False,
                }
            },
            "standard_logging_object": {"metadata": metadata, "request_tags": []},
        }
        secrets = tuple(os.environ.get(name, "") for name in _SECRET_ENV)
        self._logger().log_event_on_langfuse(
            kwargs=_masked(local, secrets),
            response_obj=_masked(response_obj, secrets),
            start_time=start_time,
            end_time=end_time,
            level="ERROR" if failed else "DEFAULT",
            status_message=_masked(
                str(kwargs.get("exception") or "Unknown upstream error"), secrets
            )
            if failed
            else None,
        )

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        try:
            await asyncio.to_thread(self._emit, kwargs, response_obj, start_time, end_time)
        except Exception:
            # Error bodies may contain credentials. Telemetry never changes inference.
            log.error("Candidate native Langfuse callback failed; observation may be lost")

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        try:
            await asyncio.to_thread(self._emit, kwargs, response_obj, start_time, end_time, True)
        except Exception:
            log.error("Candidate native Langfuse callback failed; observation may be lost")

    def flush(self):
        if self._native is not None:
            self._native.flush()


native_langfuse = NativeLangfuse()
