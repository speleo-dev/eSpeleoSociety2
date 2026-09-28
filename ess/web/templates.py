"""Jinja2 environment shared by all pages, with Slovak labels for enums."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from ess.models import AdminRole, MembershipEndReason, MembershipStatus
from ess.services.members import SssStatus

templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

# Keyed by (enum type, value): several enums share values (e.g. "member").
_LABELS = [
    (MembershipStatus.CANDIDATE, "čakateľ"),
    (MembershipStatus.PENDING_ACTIVATION, "čaká na aktiváciu"),
    (MembershipStatus.MEMBER, "člen"),
    (MembershipStatus.SUSPENDED, "pozastavené"),
    (MembershipEndReason.STATUS_CHANGE, "zmena stavu"),
    (MembershipEndReason.TERMINATED, "ukončené"),
    (MembershipEndReason.EXPELLED, "vylúčenie zo SSS"),
    (SssStatus.MEMBER, "člen SSS"),
    (SssStatus.AWAITING_DECISION, "čaká na rozhodnutie predsedníctva"),
    (SssStatus.ENDED, "členstvo v SSS ukončené"),
    (SssStatus.EXPELLED, "vylúčený zo SSS"),
    (SssStatus.NEVER, "bez členstva"),
    (AdminRole.ADMIN, "administrátor"),
    (AdminRole.SYSTEM_ADMIN, "systémový administrátor"),
]

ERRORS = {
    "member_expelled": "Člen je vylúčený zo SSS.",
    "invalid_transition": "Táto zmena stavu nie je povolená.",
    "membership_not_open": "Členstvo už nie je platné.",
    "already_in_club": "Člen už v tejto skupine je.",
    "sss_membership_already_ended": "Členstvo v SSS už je ukončené.",
    "club_without_candidates": "Skupina nepoužíva čakateľov.",
    "admin": "Na túto akciu nemáte oprávnenie.",
    "club_manager": "Na túto akciu nemáte oprávnenie.",
    "activation": "Aktivovať člena môže len administrátor.",
    "task_not_open": "Požiadavka už bola vybavená.",
    "reason_required": "Uveďte dôvod.",
}


LABELS = {(type(k), k.value): v for k, v in _LABELS}


def label(value) -> str:
    if value is None:
        return ""
    return LABELS.get((type(value), getattr(value, "value", value)), str(getattr(value, "value", value)))


def fmt_date(value) -> str:
    return value.strftime("%d. %m. %Y") if value else ""


TASK_LABELS = {
    "member_activation": "Aktivácia člena",
    "sss_decision": "Rozhodnutie o členstve v SSS",
}

RESOLUTION_LABELS = {
    "activated": "aktivovaný",
    "rejected": "zamietnuté",
    "withdrawn": "návrh stiahnutý",
    "terminated": "členstvo v skupine ukončené",
    "rejoined": "zaradený do skupiny",
    "sss_ended": "členstvo v SSS ukončené",
    "expelled": "vylúčený zo SSS",
}


def task_label(task_type: str) -> str:
    return TASK_LABELS.get(task_type, task_type)


def resolution_label(resolution: str | None) -> str:
    return RESOLUTION_LABELS.get(resolution or "", resolution or "")


def task_description(task) -> str:
    """One line saying what the administrator is asked to do."""
    if task.task_type == "member_activation":
        if (task.context or {}).get("from_status") == "candidate":
            return "Predseda skupiny navrhuje povýšiť čakateľa na člena. Aktivujte po doručení podkladov."
        return "Nový člen navrhnutý predsedom skupiny. Aktivujte po doručení podkladov."
    if task.task_type == "sss_decision":
        return "Ukončil členstvo vo všetkých skupinách. Zapíšte rozhodnutie predsedníctva."
    return ""


templates.env.filters["label"] = label
templates.env.filters["date"] = fmt_date
templates.env.filters["task_label"] = task_label
templates.env.filters["resolution_label"] = resolution_label
templates.env.filters["task_description"] = task_description
