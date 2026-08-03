"""Typed contracts shared by the FTS-LS service, API and state store.

The device firmware can add fields to detailed ``show`` responses. Known fields are
typed explicitly while every normalized section remains open to additional values.
"""

from typing import Any, Literal, TypedDict


class FtsModule(TypedDict, total=False):
    """Normalized status of the uplink or one physical P1-P7 slot."""

    name: str
    type: str
    state: str
    connectors: list[str]
    description: str
    optical_power: float | None
    optical_power_display: str
    noise_lf: float | None
    noise_hf: float | None
    jitter: float | None
    distance_km: float | None
    additional_gain_db: float | None
    polarization_control: bool
    polarization_controller_speed: str
    polarization_controller_mode: str


class FtsCommandResult(TypedDict, total=False):
    """Result of the most recently completed station command."""

    action: str
    output: str
    error: str
    completed_at: str


class FtsStatus(TypedDict):
    """Stable top-level shape returned for every FTS-LS status snapshot."""

    profile: Literal["fts-ls"]
    laser: dict[str, Any]
    uplink: FtsModule
    ports: list[FtsModule]
    synth: dict[str, Any]
    tec: dict[str, Any]
    power: dict[str, Any]
    system: dict[str, Any]
    last_command: FtsCommandResult | None
