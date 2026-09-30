"""Jinja2 environment shared by all pages, with Slovak labels for enums."""

from datetime import date
from decimal import Decimal
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
    (SssStatus.AWAITING_DECISION, "člen SSS bez skupiny – čaká na rozhodnutie"),
    (SssStatus.ENDED, "členstvo v SSS ukončené"),
    (SssStatus.EXPELLED, "vylúčený zo SSS"),
    (SssStatus.NEVER, "bez členstva"),
    (AdminRole.ADMIN, "administrátor"),
    (AdminRole.SYSTEM_ADMIN, "superadmin"),
]

ERRORS = {
    "member_expelled": "Člen je vylúčený zo SSS.",
    "invalid_transition": "Táto zmena stavu nie je povolená.",
    "membership_not_open": "Členstvo už nie je platné.",
    "already_in_club": "Člen už v tejto skupine je.",
    "sss_membership_already_ended": "Členstvo v SSS už je ukončené.",
    "club_without_candidates": "Skupina nepoužíva čakateľov.",
    "admin": "Na túto akciu nemáte oprávnenie.",
    "admin_only": "Platbu v hotovosti eviduje administrátor (nie systémový administrátor).",
    "club_manager": "Na túto akciu nemáte oprávnenie.",
    "activation": "Aktivovať člena môže len administrátor.",
    "task_not_open": "Požiadavka už bola vybavená.",
    "reason_required": "Uveďte dôvod.",
    "member_required": "Vyberte člena.",
    "name_required": "Vyplňte meno (názov).",
    "invalid_email": "Neplatná e-mailová adresa.",
    "birth_date_required": "Zadajte dátum narodenia.",
    "card_number_required": "Zadajte číslo preukazu SSS.",
    "member_since_required": "Zadajte rok, odkedy ste členom SSS (napr. 1995).",
    "club_required": "Vyberte skupinu.",
    "gdpr_consent_required": "Bez súhlasu so spracovaním osobných údajov nie je možné eCP vydať.",
    "application_not_open": "Žiadosť už bola vybavená alebo vypršala.",
    "application_not_found": "Žiadosť neexistuje.",
    "ecp_needs_email": "Na vydanie eCP treba e-mail člena.",
    "card_needs_email": "Člen nemá e-mail – kartičku stiahnite a vytlačte.",
    "card_already_issued": "Na tento rok už kartička vydaná bola. Stiahnite ju znova; novú môže vydať len administrátor ako náhradu (stratená / ukradnutá / poškodená).",
    "card_not_available": "Kartička už neplatí alebo ju nemožno znova stiahnuť.",
    "invalid_sticker_template": "Šablóna musí byť PNG 256 × 256 px s priehľadným pozadím a sivými farbami #000000, #606060, #404040.",
    "sticker_locked": "Ročná známka je už zverejnená; ďalšiu možno pripraviť v nasledujúcom období platby členského.",
    "sticker_wrong_year": "Teraz možno pripraviť známku len na rok obdobia platby členského.",
    "bulk_payment_not_open": "Hromadná platba na tento rok sa otvorí po zverejnení ročnej známky SSS.",
    "sticker_not_published": "Najprv zverejnite ročnú známku; až potom sa otvorí platba členského cez eCP.",
    "invalid_card_year": "Kartičku možno vydať na tento rok, na nasledujúci len v období platby členského.",
    "ecp_member_not_eligible": "eCP môže dostať len člen (nie čakateľ).",
    "member_not_in_sss": "Člen už nie je členom SSS – eCP nemožno vydať.",
    "member_has_ecp": "Člen už má vydaný eCP.",
    "wallet_error": "Google Wallet preukaz nevytvoril. Skúste to znova neskôr.",
    "photo_missing": "Pôvodná fotka už nie je k dispozícii.",
    "photo_too_small": "Fotka je príliš malá (kratšia strana aspoň 240 px).",
    "photo_crop_too_small": "Vybraný výrez je príliš malý – zväčšite ho.",
    "invalid_country": "Krajina musí byť dvojpísmenový kód (napr. SK, CZ).",
    "invalid_web": "Web musí začínať http:// alebo https://",
    "invalid_date": "Neplatný dátum.",
    "card_number_in_use": "Toto číslo preukazu už má iný člen.",
    "club_name_in_use": "Skupina s týmto názvom už existuje.",
    "club_code_in_use": "Tento kód skupiny už má iná skupina.",
    "invalid_club_code": "Kód skupiny môže obsahovať len A–Z, 0–9, - a _ (najviac 20 znakov).",
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
    "image_missing": "Vyberte súbor s obrázkom.",
    "image_too_large": "Obrázok je príliš veľký (najviac 5 MB).",
    "invalid_image": "Súbor nie je podporovaný obrázok (PNG, JPEG, WebP, GIF).",
    "media_store_not_configured": "Úložisko obrázkov nie je nastavené (ESS_MEDIA_BUCKET).",
    "certificate_type_exists": "Tento typ certifikátu už existuje.",
    "super_admin_is_configured": "Tento účet je hlavný systémový administrátor (nastavené na serveri).",
    "cannot_revoke_self": "Nemôžete odobrať prístup sebe.",
    "system_admin": "Túto akciu môže vykonať len superadmin.",
    "invalid_value": "Neplatná hodnota.",
    "already_expelled": "Člen už je vylúčený.",
    "member_edit": "Na úpravu údajov tohto člena nemáte oprávnenie.",
    "reduced_fee": "Zľavnené členské môže nastaviť len administrátor.",
    "member_not_found": "Člen neexistuje.",
    "club_not_found": "Skupina neexistuje.",
    "member_payment": "Na túto akciu nemáte oprávnenie.",
    "fee_already_paid": "Členské na tento rok už je zaplatené.",
    "payment_account_not_configured": "Nie je nastavený IBAN pre členské (Nastavenia → Členské).",
    "no_members_selected": "Vyberte aspoň jedného člena.",
    "member_not_payable": "Niektorý z vybraných členov už má zaplatené alebo je v inej hromadnej platbe.",
    "reference_not_open": "Platobný odkaz už nie je otvorený (je zaplatený alebo zrušený).",
    "note_required": "Doplňte poznámku.",
    "club_has_no_chair": "Skupina nemá zadaného predsedu.",
    "club_chair": "Túto akciu môže vykonať len predseda skupiny.",
    "club_already_delegated": "Skupinu už spravuje zástupca – najprv prevezmite správu.",
    "club_not_delegated": "Skupina nemá zástupcu predsedu.",
    "portal_not_available": "Portál nie je dostupný – odkaz je neplatný alebo váš eCP nie je aktívny.",
    "portal_needs_email": "V evidencii nemáte e-mail. Kontaktujte predsedu svojej skupiny.",
    "too_many_codes": "Kódov bolo odoslaných priveľa. Skúste to znova o hodinu.",
    "notification_required": "Vyplňte nadpis aj text notifikácie.",
    "notification_too_long": "Nadpis môže mať najviac 100 znakov a text 500 znakov.",
    "notification_limit": "Za posledných 24 hodín už boli odoslané 3 notifikácie (limit Google Wallet). Skúste to neskôr.",
    "cave_required": "Vyplňte jaskyňu.",
    "invalid_return_time": "Plánovaný návrat musí byť v budúcnosti (najviac 14 dní).",
    "trip_already_open": "Už máte nahlásený vstup do jaskyne – najprv potvrďte návrat.",
    "trip_not_open": "Nemáte nahlásený vstup do jaskyne.",
    "device_not_found": "Zariadenie sa nenašlo alebo už je odhlásené.",
    "passkey_failed": "Prihlásenie passkey sa nepodarilo. Skúste to znova alebo sa prihláste kódom z e-mailu.",
    "code_wrong": "Nesprávny kód. Skúste to znova.",
    "code_expired": "Kód vypršal alebo bol viackrát zadaný nesprávne. Požiadajte o nový.",
    "statement_already_imported": "Tento výpis už bol nahratý.",
    "invalid_statement": "Súbor nie je výpis vo zvolenom formáte.",
    "unknown_statement_format": "Neznámy formát výpisu.",
    "reference_not_found": "Referencia neexistuje.",
    "statement_too_large": "Súbor je príliš veľký (najviac 10 MB).",
    "delegate_not_eligible": "Zástupcom môže byť len člen skupiny (stav člen), ktorý ju má ako primárnu, a nie predseda.",
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
    "ecp_issue": "Vydanie eCP",
    "payment_unmatched": "Nespárovaná platba",
    "payment_overpaid": "Preplatok",
}

RESOLUTION_LABELS = {
    "assigned": "priradená k referencii",
    "resolved": "vybavené",
    "activated": "aktivovaný",
    "rejected": "zamietnuté",
    "withdrawn": "návrh stiahnutý",
    "terminated": "členstvo v skupine ukončené",
    "rejoined": "zaradený do skupiny",
    "sss_ended": "členstvo v SSS ukončené",
    "approved": "eCP vydaný",
    "expelled": "vylúčený zo SSS",
}


def task_label(task_type: str) -> str:
    return TASK_LABELS.get(task_type, task_type)


def resolution_label(resolution: str | None) -> str:
    return RESOLUTION_LABELS.get(resolution or "", resolution or "")


def task_description(task) -> str:
    """One line saying what the administrator is asked to do."""
    if task.task_type == "member_activation":
        if (task.context or {}).get("issue_ecp"):
            return "Nový člen navrhnutý predsedom skupiny, žiada o eCP. Po aktivácii mu príde e-mail na nahratie fotky."
        if (task.context or {}).get("from_status") == "candidate":
            return "Predseda skupiny navrhuje povýšiť čakateľa na člena. Aktivujte po doručení podkladov."
        return "Nový člen navrhnutý predsedom skupiny. Aktivujte po doručení podkladov."
    if task.task_type == "sss_decision":
        return "Nie je v žiadnej skupine (členom SSS ostáva). Rozhodnite o zaradení do „SSS – nezaradení“ alebo o ukončení členstva v SSS."
    if task.task_type == "ecp_issue":
        return "Žiadosť o eCP s fotkou. Skontrolujte fotku a schváľte alebo zamietnite."
    ctx = task.context or {}
    amount = money(Decimal(ctx["amount"])) if ctx.get("amount") else ""
    if task.task_type == "payment_unmatched":
        return (f"Platba {amount} z {fmt_date(date.fromisoformat(ctx['booked_on']))} bez známej referencie. "
                "Priraďte ju k referencii alebo vybavte ručne (napr. vrátenie).")
    if task.task_type == "payment_overpaid":
        return (f"Preplatok {money(Decimal(ctx.get('overpaid', '0')))} (platba {amount}, referencia {ctx.get('code', '')}, "
                f"rok {ctx.get('year', '')}). Vráťte ho alebo ho ponechajte ako dar.")
    return ""


def membership_icon(status, primary: bool = True) -> str:
    """Icon file for a club membership; an active membership in a non-primary club is shown as "guest"."""
    value = getattr(status, "value", status)
    if value == "member" and not primary:
        return "guest"
    return value


def sss_icon(sss_status) -> str:
    value = getattr(sss_status, "value", sss_status)
    return {"expelled": "expelled", "member": "member"}.get(value, "no_club")


ICON_LEGEND = [
    ("member", "člen"), ("candidate", "čakateľ"), ("pending_activation", "čaká na aktiváciu"),
    ("suspended", "pozastavené"), ("guest", "člen v ďalšej (neprimárnej) skupine"), ("chair", "predseda skupiny"),
    ("no_club", "bez skupiny"), ("expelled", "vylúčený zo SSS"), ("reduced_fee", "zľavnené členské"),
]

templates.env.filters["membership_icon"] = membership_icon
templates.env.filters["sss_icon"] = sss_icon
templates.env.globals["ICON_LEGEND"] = ICON_LEGEND
templates.env.filters["label"] = label
templates.env.filters["date"] = fmt_date


def local_time(value) -> str:
    """Date and time in Slovak local time (Cloud Run runs in UTC)."""
    from zoneinfo import ZoneInfo

    return value.astimezone(ZoneInfo("Europe/Bratislava")).strftime("%d.%m.%Y %H:%M:%S") if value else ""


templates.env.filters["local_time"] = local_time

ECP_STATE_LABELS = {"active": "aktívny", "inactive": "neaktívny", "revoked": "zrušený"}
templates.env.filters["ecp_state_label"] = lambda state: ECP_STATE_LABELS.get(state, state)

CARD_REASON_LABELS = {"lost": "nahlásená ako stratená", "stolen": "nahlásená ako ukradnutá",
                      "damaged": "nahradená (poškodená)", None: "neplatná"}
templates.env.filters["card_reason_label"] = lambda reason: CARD_REASON_LABELS.get(reason, "neplatná")
PAYMENT_STATUS_LABELS = {"open": "čaká na platbu", "partial": "zaplatené čiastočne", "paid": "zaplatené",
                         "cancelled": "zrušený"}
templates.env.filters["payment_status_label"] = lambda status: PAYMENT_STATUS_LABELS.get(status, status)


def money(value) -> str:
    """Amount in Slovak format, e.g. 15,00 €."""
    return f"{value:.2f}".replace(".", ",") + " €" if value is not None else ""


templates.env.filters["money"] = money


def short_name(value: str) -> str:
    """"Ladislav Gagyi" -> "Ladislav G." (header of the administration)."""
    parts = (value or "").split()
    if len(parts) < 2:
        return value or ""
    return f"{parts[0]} {parts[-1][0]}."


templates.env.filters["short_name"] = short_name


def two_lines(value: str):
    """Full name in two lines (first names / last name) to save space in the header."""
    from markupsafe import Markup, escape

    parts = (value or "").split()
    if len(parts) < 2:
        return escape(value or "")
    return Markup(f"{escape(' '.join(parts[:-1]))}<br>{escape(parts[-1])}")


templates.env.filters["two_lines"] = two_lines
FEE_METHOD_LABELS = {"member": "odkaz člena", "bulk": "hromadná platba", "manual": "ručne"}
templates.env.filters["fee_method_label"] = lambda method: FEE_METHOD_LABELS.get(method, "")
templates.env.filters["task_label"] = task_label
templates.env.filters["resolution_label"] = resolution_label
templates.env.filters["task_description"] = task_description
