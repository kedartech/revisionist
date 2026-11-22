"""The Autumn 1941 names the production rules keep for a stored game (PRL).

A game whose board was compiled before PRL, or that has no board, holds no ``production``
keys; ``production`` reads these names for it instead, so its finding and its priority act
exactly as they did. A game the world compiles today reads the world's keys and never this
module.
"""

FINDING = "lend_lease_finding"
"""The aid finding's form."""
RECIPIENT, SHARE = "recipient", "share_pct"
"""The finding's parameters: the nation it allocates to, and the share in per cent."""
FUND = "lend_lease_second_appropriation"
"""The figure the finding draws on."""
ELIGIBLE_NATION, ELIGIBLE_FLAG = "ussr", "soviet_lend_lease_eligible"
"""The one nation a finding makes eligible, and the flag it sets to 1."""
PRIORITY, SECTOR, GROWS = "production_priority", "sector", "merchant_ships"
"""The priority's form, its parameter, and the choice that grows a lift pool."""


def share_figure(recipient: object) -> str:
    """The key of the figure a finding writes the recipient's share to."""
    return f"lend_lease_share_{recipient}"
