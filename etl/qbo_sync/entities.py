"""QBO entities that qbo_sync lands in qbo.raw_entity (spec §1, §3.1, §3.2).

The list is the contract between the extractor and the dbt staging models: an entity that is
not listed here is never landed.
"""

from __future__ import annotations

# Name-list entities. A plain QBO query returns only Active = true objects for these, so the
# backfill adds `where Active in (true, false)`: inactive accounts can still carry GL history.
NAME_LISTS: tuple[str, ...] = ("Account", "Item", "Customer", "Vendor", "Class")

# Posting transactions of spec §3.1, plus RefundReceipt (spec §3.2 flips its sign).
TRANSACTIONS: tuple[str, ...] = (
    "Invoice",
    "SalesReceipt",
    "CreditMemo",
    "RefundReceipt",
    "Bill",
    "Purchase",
    "JournalEntry",
)

# Budget comes from the QBO Budget entity (USER 2026-09-26) and feeds fact_budget.
BUDGETS: tuple[str, ...] = ("Budget",)

# P&L-affecting entities the spec does not list. Landed raw only (cheap); no dbt transform
# exists for them yet (out of scope 2026-09-26). Deposit lines can post to income accounts;
# VendorCredit lines reduce expense accounts.
LANDED_ONLY: tuple[str, ...] = ("Deposit", "VendorCredit")

ALL_ENTITIES: tuple[str, ...] = NAME_LISTS + TRANSACTIONS + BUDGETS + LANDED_ONLY

# Intuit: CDC covers every entity except JournalCode, TimeActivity, TaxAgency, TaxCode and
# TaxRate, so all of the above (Budget included) take part in the daily cdc run.
CDC_ENTITIES: tuple[str, ...] = ALL_ENTITIES

_BY_LOWER = {name.lower(): name for name in ALL_ENTITIES}


def canonical(name: str) -> str:
    """Map a CLI entity argument (any case) to its QBO name; ValueError if it is not landed."""
    try:
        return _BY_LOWER[name.lower()]
    except KeyError:
        raise ValueError(
            f"unknown entity {name!r}; valid entities: {', '.join(ALL_ENTITIES)}"
        ) from None
