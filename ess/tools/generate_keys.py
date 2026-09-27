"""Print new random keys for ESS_PII_KEYS and ESS_BLIND_INDEX_KEY.

Usage: python -m ess.tools.generate_keys

Store the output only in Secret Manager (or a local, git-ignored .env for development).
"""

from datetime import date

from ess.security.crypto import generate_key


def main() -> None:
    key_id = f"k{date.today():%Y%m}"
    print(f"ESS_PII_KEYS={key_id}:{generate_key()}")
    print(f"ESS_BLIND_INDEX_KEY={generate_key()}")


if __name__ == "__main__":
    main()
