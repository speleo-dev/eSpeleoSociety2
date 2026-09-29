"""Business rules and permissions."""

# Registers the flush events that keep the eCP state in line with SSS membership (R25).
from ess.services import ecp_state  # noqa: E402,F401
# Registers the flush events that end a club chair delegation when it no longer applies (R37).
from ess.services import delegations  # noqa: E402,F401
