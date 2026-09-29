"""Bank statement parsers. Each returns incoming payments as `ParsedTransaction` (in memory only)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


class StatementError(Exception):
    """The file is not a statement in the chosen format. `code` is used for UI messages."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class ParsedTransaction:
    bank_ref: str  # unique id of the transaction in the bank (protection against double import)
    booked_on: date
    amount: Decimal
    currency: str
    payer_reference: str | None  # "referencia platiteľa" (end-to-end id)
    payer_name: str | None = None  # personal data: encrypted in the database
    payer_iban: str | None = None
    message: str | None = None


def parse(file_format: str, data: bytes) -> list[ParsedTransaction]:
    from ess.banking import camt053

    parsers = {camt053.FORMAT: camt053.parse}
    if file_format not in parsers:
        raise StatementError("unknown_statement_format")
    return parsers[file_format](data)


FORMATS = {"camt053": "camt.053 (XML)"}
