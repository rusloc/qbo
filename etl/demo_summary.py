"""Expected warehouse numbers for the demo dataset, computed from demo_data/*.json in Python.

An independent (Decimal-only) implementation of spec 3.1 line explosion (sales lines: the
line's ItemAccountRef, else the item's IncomeAccountRef), 3.2 sign normalization and 3.3
section defaults; vw_fact_gl counts P&L lines only (Revenue / Expense accounts). It prints:
- expected row counts per raw entity and per dim_* / fact_* table and vw_* view after `dbt build`;
- storyline checks: GM% by year, Q4 share, Marketing vs budget from month 15, stable Rent/Software;
- P&L by year x stmt_section, to compare with the `qbo_demo_check` dbt operation (same numbers
  must come out of the warehouse).

Usage: etl/.venv/Scripts/python etl/demo_summary.py [--dir demo_data]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "demo_data"
FIRST_MONTH = date(2024, 9, 1)
ZERO = Decimal(0)

SECTION_BY_TYPE = {
    "Income": "Revenue",
    "Cost of Goods Sold": "COGS",
    "Expense": "OpEx",
    "Other Income": "OtherInc",
    "Other Expense": "OtherExp",
}
CREDIT_NATURAL = {"Revenue", "Liability", "Equity"}
POSTING = {
    "SalesItemLineDetail",
    "AccountBasedExpenseLineDetail",
    "ItemBasedExpenseLineDetail",
    "JournalEntryLineDetail",
    "DiscountLineDetail",
}
NON_POSTING = {"SubTotalLineDetail", "DescriptionOnly"}
TXN_TYPES = ("Invoice", "SalesReceipt", "CreditMemo", "RefundReceipt", "Bill", "Purchase", "JournalEntry")


@dataclass(frozen=True)
class GlLine:
    txn_type: str
    txn_id: str
    line_num: int
    txn_date: date
    account_id: str
    class_id: str | None
    amount_signed: Decimal
    is_voided: bool


def load(folder: Path) -> dict[str, list[dict]]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"), parse_float=Decimal)
        for p in sorted(folder.glob("*.json"))
    }


def is_voided(doc: dict) -> bool:
    note = (doc.get("PrivateNote") or "").lower()
    return note.startswith("voided") and Decimal(doc.get("TotalAmt", 0)) == 0


def explode(data: dict[str, list[dict]]) -> list[GlLine]:
    accounts = {a["Id"]: a for a in data["Account"]}
    items = {i["Id"]: i for i in data["Item"]}
    out: list[GlLine] = []
    for txn_type in TXN_TYPES:
        for doc in data.get(txn_type, []):
            credit_doc = txn_type in ("CreditMemo", "RefundReceipt") or (
                txn_type == "Purchase" and doc.get("Credit") is True
            )
            for line_num, line in enumerate(doc.get("Line", []), start=1):
                detail_type = line["DetailType"]
                if detail_type in NON_POSTING:
                    continue
                if detail_type not in POSTING:
                    raise ValueError(f"unknown DetailType {detail_type}")
                detail = line[detail_type]
                if detail_type == "SalesItemLineDetail":
                    # The line's ItemAccountRef (posting account) wins; else the item's current
                    # IncomeAccountRef (USER 2026-09-26).
                    posted = detail.get("ItemAccountRef") or items[detail["ItemRef"]["value"]]["IncomeAccountRef"]
                    account_id = posted["value"]
                    side = "Debit" if credit_doc else "Credit"
                elif detail_type == "ItemBasedExpenseLineDetail":
                    account_id = items[detail["ItemRef"]["value"]]["ExpenseAccountRef"]["value"]
                    side = "Credit" if credit_doc else "Debit"
                elif detail_type == "DiscountLineDetail":
                    account_id = detail["DiscountAccountRef"]["value"]
                    side = "Credit" if credit_doc else "Debit"
                elif detail_type == "JournalEntryLineDetail":
                    account_id = detail["AccountRef"]["value"]
                    side = detail["PostingType"]
                else:  # AccountBasedExpenseLineDetail
                    account_id = detail["AccountRef"]["value"]
                    side = "Credit" if credit_doc else "Debit"
                natural = "Credit" if accounts[account_id]["Classification"] in CREDIT_NATURAL else "Debit"
                amount = Decimal(line["Amount"])
                class_ref = detail.get("ClassRef") or doc.get("ClassRef")
                out.append(GlLine(
                    txn_type,
                    doc["Id"],
                    line_num,
                    date.fromisoformat(doc["TxnDate"]),
                    account_id,
                    class_ref["value"] if class_ref else None,
                    amount if side == natural else -amount,
                    is_voided(doc),
                ))
    return out


def month_index(d: date) -> int:
    return (d.year - FIRST_MONTH.year) * 12 + d.month - FIRST_MONTH.month + 1


def pct(num: Decimal, den: Decimal) -> str:
    return f"{(num / den * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%" if den else "n/a"


def expected_counts(data: dict[str, list[dict]], gl: list[GlLine]) -> dict[str, int]:
    dates = [date.fromisoformat(d["TxnDate"]) for t in data.values() for d in t if "TxnDate" in d]
    for b in data.get("Budget", []):
        dates += [date.fromisoformat(b["StartDate"]), date.fromisoformat(b["EndDate"])]
    first, last = date(min(dates).year, 1, 1), date(max(dates).year, 12, 31)
    budget_keys = {
        (row["BudgetDate"][:7], row["AccountRef"]["value"], (row.get("ClassRef") or {}).get("value"))
        for b in data.get("Budget", [])
        if b.get("Active", True) and b["BudgetType"] == "ProfitAndLoss"
        for row in b["BudgetDetail"]
    }
    pnl = {a["Id"]: a["Classification"] in ("Revenue", "Expense") for a in data["Account"]}
    counts = {f"raw_entity.{name}": len(rows) for name, rows in data.items()}
    counts["raw_entity (total)"] = sum(len(rows) for rows in data.values())
    counts |= {
        "dim_account": len(data["Account"]),
        "dim_customer": len(data["Customer"]),
        "dim_vendor": len(data["Vendor"]),
        "dim_class": len(data["Class"]),
        "dim_date": (last - first).days + 1,
        "fact_gl": len(gl),
        # vw_fact_gl: P&L lines only (classification Revenue / Expense; USER 2026-09-26).
        "vw_fact_gl": sum(1 for g in gl if not g.is_voided and pnl[g.account_id]),
        "fact_budget": len(budget_keys),
    }
    return counts


def pnl_by_year(data: dict[str, list[dict]], gl: list[GlLine]) -> dict[int, dict[str, Decimal]]:
    section = {a["Id"]: SECTION_BY_TYPE.get(a["AccountType"]) for a in data["Account"]}
    out: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for g in gl:
        if g.is_voided or section[g.account_id] is None:
            continue
        year = 1 if month_index(g.txn_date) <= 12 else 2
        out[year][section[g.account_id]] += g.amount_signed
    return out


def storyline(data: dict[str, list[dict]], gl: list[GlLine]) -> dict[str, object]:
    accounts = {a["Id"]: a for a in data["Account"]}
    by_name = {a["FullyQualifiedName"]: a["Id"] for a in data["Account"]}
    pnl = pnl_by_year(data, gl)
    result: dict[str, object] = {}
    for year, s in sorted(pnl.items()):
        gp = s["Revenue"] - s["COGS"]
        ni = gp - s["OpEx"] + s["OtherInc"] - s["OtherExp"]
        result[f"year{year}"] = {
            "revenue": s["Revenue"], "cogs": s["COGS"], "gross_profit": gp, "gm_pct": gp / s["Revenue"] * 100,
            "opex": s["OpEx"], "net_income": ni, "ni_pct": ni / s["Revenue"] * 100,
        }
    rev_q4: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for g in gl:
        if not g.is_voided and accounts[g.account_id]["AccountType"] == "Income" and g.txn_date.month >= 10:
            rev_q4[1 if month_index(g.txn_date) <= 12 else 2] += g.amount_signed
    result["q4_share"] = {y: rev_q4[y] / pnl[y]["Revenue"] * 100 for y in (1, 2)}

    marketing = {by_name["Marketing:Digital Advertising"], by_name["Marketing:Trade Shows & Promotions"]}
    actual = defaultdict(lambda: ZERO)
    for g in gl:
        if not g.is_voided and g.account_id in marketing:
            actual[month_index(g.txn_date)] += g.amount_signed
    budget = defaultdict(lambda: ZERO)
    for b in data["Budget"]:
        if not b["Active"]:
            continue
        for row in b["BudgetDetail"]:
            k = month_index(date.fromisoformat(row["BudgetDate"]))
            if 1 <= k <= 24 and row["AccountRef"]["value"] in marketing:
                budget[k] += Decimal(row["Amount"])
    result["marketing"] = {k: (actual[k], budget[k]) for k in range(1, 25)}

    stable = {}
    for name in ("Occupancy:Rent", "Software & Subscriptions"):
        per_month = defaultdict(lambda: ZERO)
        for g in gl:
            if not g.is_voided and g.account_id == by_name[name]:
                per_month[month_index(g.txn_date)] += g.amount_signed
        stable[name] = sorted(set(per_month.values()))
    result["stable"] = stable
    result["payroll_je_months"] = len({
        d["TxnDate"][:7] for d in data["JournalEntry"] if d["PrivateNote"].startswith("Payroll")
    })
    result["voided"] = [(g.txn_type, g.txn_id) for g in gl if g.is_voided]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Expected warehouse numbers for the demo dataset.")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args(argv)
    data = load(args.dir)
    gl = explode(data)

    print("Expected row counts after load_demo.py + dbt build")
    for name, n in expected_counts(data, gl).items():
        print(f"  {name:<28} {n:>7}")

    s = storyline(data, gl)
    print("\nP&L by data year (year 1 = 2024-09..2025-08, year 2 = 2025-09..2026-08; voided excluded)")
    for year in ("year1", "year2"):
        y = s[year]
        print(
            f"  {year}: revenue {y['revenue']:>13,}  cogs {y['cogs']:>13,}  gm% {y['gm_pct']:.1f}"
            f"  opex {y['opex']:>13,}  net income {y['net_income']:>12,}  ni% {y['ni_pct']:.1f}"
        )
    gm_delta = s["year2"]["gm_pct"] - s["year1"]["gm_pct"]
    print(f"  gross margin change year 2 vs year 1: {gm_delta:+.2f} pp (storyline: about -3 pp)")
    print(f"  Q4 share of revenue: year1 {s['q4_share'][1]:.1f}%  year2 {s['q4_share'][2]:.1f}%")

    print("\nMarketing (Digital Advertising + Trade Shows) actual vs budget")
    m = s["marketing"]
    for lo, hi in ((1, 14), (15, 24)):
        a = sum((m[k][0] for k in range(lo, hi + 1)), ZERO)
        b = sum((m[k][1] for k in range(lo, hi + 1)), ZERO)
        print(f"  months {lo:>2}-{hi:<2}: actual {a:>11,}  budget {b:>11,}  actual/budget {pct(a, b)}")
    for k in range(13, 25):
        a, b = m[k]
        print(f"    month {k:>2}: actual {a:>10,}  budget {b:>10,}  {pct(a, b)}")

    print("\nStable lines (distinct monthly totals)")
    for name, values in s["stable"].items():
        print(f"  {name:<26} {', '.join(f'{v:,}' for v in values)}")
    print(f"  payroll journal entries: {s['payroll_je_months']} months")
    print(f"  voided transactions (lines): {sorted(set(s['voided']))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
