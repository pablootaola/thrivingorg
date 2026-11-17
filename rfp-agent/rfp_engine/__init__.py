"""RFP engine: sourcing, recording, acquisition, screening, pricing and gate helpers.

This package holds mechanics only. Rules, rulings, team data, client data and
every private identifier (sheet IDs, Notion IDs, mailbox) live in the private
system of record and are loaded at runtime from a local config file that is
never committed. See ../README.md.
"""

__version__ = "0.1.0"
USER_AGENT = "rfp-engine/0.1 (procurement research)"
