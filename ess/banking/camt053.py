"""Parser of ISO 20022 camt.053 (bank to customer statement) – incoming payments only.

PROVISIONAL: verified against the standard, not yet against a real statement of the SSS bank.
The payer reference ("referencia platiteľa", PAYMe `PI`) is the SEPA end-to-end id (`EndToEndId`);
a structured creditor reference or the message may carry it too, so all are kept.
"""

import hashlib
from datetime import date
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree

from ess.banking import ParsedTransaction, StatementError

FORMAT = "camt053"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(node, path: str):
    """Namespace-agnostic child lookup, e.g. "NtryDtls/TxDtls"."""
    for part in path.split("/"):
        if node is None:
            return None
        node = next((c for c in node if _local(c.tag) == part), None)
    return node


def _findall(node, name: str) -> list:
    return [c for c in node if _local(c.tag) == name] if node is not None else []


def _text(node, path: str) -> str | None:
    found = _find(node, path)
    value = (found.text or "").strip() if found is not None else ""
    return value or None


def _amount(node) -> tuple[Decimal, str] | None:
    if node is None or not (node.text or "").strip():
        return None
    try:
        return Decimal(node.text.strip()), node.get("Ccy", "")
    except InvalidOperation:
        return None


def _reference(value: str | None) -> str | None:
    return None if value is None or value.upper() == "NOTPROVIDED" else value


def parse(data: bytes) -> list[ParsedTransaction]:
    try:
        root = ElementTree.fromstring(data, forbid_dtd=True)
    except Exception:  # malformed XML, DTD / entities (defusedxml)
        raise StatementError("invalid_statement") from None
    statement = _find(root, "BkToCstmrStmt")
    if statement is None:
        raise StatementError("invalid_statement")
    result = []
    for stmt in _findall(statement, "Stmt"):
        for entry in _findall(stmt, "Ntry"):
            if _text(entry, "CdtDbtInd") != "CRDT" or _text(entry, "RvslInd") == "true":
                continue  # outgoing payments and reversals are not membership fees
            booked = _text(entry, "BookgDt/Dt") or (_text(entry, "BookgDt/DtTm") or "")[:10]
            try:
                booked_on = date.fromisoformat(booked)
            except ValueError:
                raise StatementError("invalid_statement") from None
            entry_amount = _amount(_find(entry, "Amt"))
            details = [tx for d in _findall(entry, "NtryDtls") for tx in _findall(d, "TxDtls")] or [None]
            entry_ref = _text(entry, "AcctSvcrRef") or _text(entry, "NtryRef")
            for index, tx in enumerate(details):
                amount = None
                if tx is not None:
                    amount = _amount(_find(tx, "AmtDtls/TxAmt/Amt")) or _amount(_find(tx, "Amt"))
                if amount is None and len(details) == 1:
                    amount = entry_amount
                if amount is None:
                    raise StatementError("invalid_statement")
                debtor = _find(tx, "RltdPties/Dbtr") if tx is not None else None
                name = _text(debtor, "Nm") or _text(debtor, "Pty/Nm")
                iban = _text(tx, "RltdPties/DbtrAcct/Id/IBAN") if tx is not None else None
                end_to_end = _reference(_text(tx, "Refs/EndToEndId")) if tx is not None else None
                creditor_ref = _text(tx, "RmtInf/Strd/CdtrRefInf/Ref") if tx is not None else None
                message = " ".join(u.text.strip() for u in _findall(_find(tx, "RmtInf"), "Ustrd") if u.text) or None
                tx_ref = (_text(tx, "Refs/AcctSvcrRef") if tx is not None else None) or entry_ref
                if tx_ref and len(details) > 1 and tx_ref == entry_ref:
                    tx_ref = f"{tx_ref}/{index + 1}"
                if not tx_ref:  # no bank id: a stable fingerprint of the transaction
                    tx_ref = "h:" + hashlib.sha256(
                        f"{booked_on}|{amount[0]}|{iban}|{end_to_end}|{message}|{index}".encode()).hexdigest()[:40]
                result.append(ParsedTransaction(
                    bank_ref=tx_ref[:100], booked_on=booked_on, amount=amount[0], currency=amount[1] or "EUR",
                    payer_reference=end_to_end or creditor_ref, payer_name=name, payer_iban=iban, message=message))
    return result
