"""Narrowing-only policy: intersect specified lists, minimize specified ceilings."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    models: list[str] | None = Field(default=None, max_length=500)
    providers: list[str] | None = Field(default=None, max_length=100)
    max_body_bytes: int | None = Field(default=None, gt=0)
    timeout_seconds: int | None = Field(default=None, gt=0)
    key_requests_per_minute: int | None = Field(default=None, gt=0)
    application_requests_per_minute: int | None = Field(default=None, gt=0)


@dataclass(frozen=True)
class EffectivePolicy:
    models: frozenset[str]
    providers: frozenset[str]
    max_body_bytes: int | None
    timeout_seconds: int | None
    key_requests_per_minute: int | None
    application_requests_per_minute: int | None
    group_version: int
    application_version: int


def effective_policy(group: Policy, application: Policy, group_version=0, application_version=0):
    def allowed(name):
        specified = [
            frozenset(value)
            for p in (group, application)
            if (value := getattr(p, name)) is not None
        ]
        return frozenset.intersection(*specified) if specified else frozenset()

    def ceiling(name):
        specified = [value for p in (group, application) if (value := getattr(p, name)) is not None]
        return min(specified) if specified else None

    return EffectivePolicy(
        allowed("models"),
        allowed("providers"),
        ceiling("max_body_bytes"),
        ceiling("timeout_seconds"),
        ceiling("key_requests_per_minute"),
        ceiling("application_requests_per_minute"),
        group_version,
        application_version,
    )
