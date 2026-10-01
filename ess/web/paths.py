"""Base path of the administration (R48): `/admin` in development, a random string in production."""

from ess.config import get_settings


class _AdminBase:
    """Behaves like the string "/<admin_path>" in f-strings and templates (read when used, not at import)."""

    def __str__(self) -> str:
        return "/" + get_settings().admin_path

    def __add__(self, other: str) -> str:
        return str(self) + other


A = _AdminBase()
