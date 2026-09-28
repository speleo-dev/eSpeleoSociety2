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
    "member_required": "Vyberte člena.",
    "name_required": "Vyplňte meno (názov).",
    "invalid_email": "Neplatná e-mailová adresa.",
    "invalid_date": "Neplatný dátum.",
    "card_number_in_use": "Toto číslo preukazu už má iný člen.",
    "club_name_in_use": "Skupina s týmto názvom už existuje.",
    "club_required": "Vyberte skupinu.",
    "club_not_allowed": "Pri tejto funkcii sa skupina nezadáva.",
    "club_inactive": "Skupina nie je aktívna.",
    "invalid_status": "Neplatný stav.",
    "chair_must_be_club_member": "Predseda musí byť členom tejto skupiny (stav člen).",
    "holder_must_be_member": "Funkciu môže zastávať len člen SSS (stav člen).",
    "unaffiliated_club_has_no_chair": "Klub „SSS – nezaradení“ nemá predsedu.",
    "unaffiliated_club_cannot_be_deactivated": "Klub „SSS – nezaradení“ sa nedá deaktivovať.",
    "position_not_open": "Funkcia už je ukončená.",
    "invalid_period": "Dátum „do“ je skôr ako „od“.",
    "url_must_be_https": "Odkaz musí začínať https://",
    "certificate_type_exists": "Tento typ certifikátu už existuje.",
    "super_admin_is_configured": "Tento účet je hlavný systémový administrátor (nastavené na serveri).",
    "cannot_revoke_self": "Nemôžete odobrať prístup sebe.",
    "system_admin": "Túto akciu môže vykonať len systémový administrátor.",
    "invalid_value": "Neplatná hodnota.",
    "already_expelled": "Člen už je vylúčený.",
    "member_edit": "Na úpravu údajov tohto člena nemáte oprávnenie.",
    "reduced_fee": "Zľavnené členské môže nastaviť len administrátor.",
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
