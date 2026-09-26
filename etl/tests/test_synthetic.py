"""generate_synthetic.py: determinism, QBO shapes, internal consistency and the spec storylines."""

import json
from datetime import date
from decimal import Decimal

import pytest

import demo_summary
import generate_synthetic as gen

TXN_TYPES = ("Invoice", "SalesReceipt", "CreditMemo", "Bill", "Purchase", "JournalEntry")
SALES = ("Invoice", "SalesReceipt", "CreditMemo")


@pytest.fixture(scope="module")
def entities():
    return gen.generate()


@pytest.fixture(scope="module")
def files(tmp_path_factory, entities):
    out = tmp_path_factory.mktemp("demo")
    gen.write(entities, out)
    return out


def walk(obj):
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def test_rerun_is_byte_identical(tmp_path, entities):
    first = gen.write(entities, tmp_path / "a")
    second = gen.write(gen.generate(), tmp_path / "b")
    assert first == second
    for name in first:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_no_float_anywhere(entities):
    assert not any(isinstance(v, float) for v in walk(entities))


def test_files_round_trip_with_decimal(files, entities):
    for name, rows in entities.items():
        raw = (files / f"{name}.json").read_bytes()
        assert raw.isascii() and b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf")
        assert json.loads(raw.decode("ascii"), parse_float=Decimal) == rows


def test_to_json_rejects_float_and_keeps_decimal_text():
    with pytest.raises(TypeError):
        gen.to_json({"Amount": 0.1})
    assert gen.to_json({"Amount": Decimal("1234.50"), "Qty": 3, "Ok": True}) == '{"Amount":1234.50,"Qty":3,"Ok":true}'
    assert gen.to_json(Decimal("1E+2")) == "100"


def test_size_and_window(entities):
    txns = [d for t in TXN_TYPES for d in entities[t]]
    assert 2300 <= len(txns) <= 2700
    dates = {date.fromisoformat(d["TxnDate"]) for d in txns}
    assert min(dates) >= date(2024, 9, 1) and max(dates) <= date(2026, 8, 31)
    assert len({(d.year, d.month) for d in dates}) == 24


def test_ids_unique(entities):
    for name, rows in entities.items():
        ids = [r["Id"] for r in rows]
        assert len(ids) == len(set(ids)), name
    txn_ids = [d["Id"] for t in TXN_TYPES for d in entities[t]]
    assert len(txn_ids) == len(set(txn_ids))  # one transaction Id sequence, as in QBO


def test_every_reference_resolves(entities):
    ids = {name: {r["Id"] for r in entities[name]} for name in ("Account", "Item", "Customer", "Vendor", "Class")}
    ref_target = {
        "AccountRef": "Account", "IncomeAccountRef": "Account", "ExpenseAccountRef": "Account",
        "DiscountAccountRef": "Account", "APAccountRef": "Account", "DepositToAccountRef": "Account",
        "ItemAccountRef": "Account", "ParentRef": None, "ItemRef": "Item", "CustomerRef": "Customer",
        "VendorRef": "Vendor", "ClassRef": "Class",
    }
    checked = 0
    for obj in walk(entities):
        if not isinstance(obj, dict):
            continue
        for key, target in ref_target.items():
            if key in obj and target:
                assert obj[key]["value"] in ids[target], (key, obj[key])
                checked += 1
        if "EntityRef" in obj:
            assert obj["EntityRef"]["value"] in ids[obj["EntityRef"]["type"]]
    assert checked > 5000


def test_every_spec_detail_type_present(entities):
    types = {line["DetailType"] for t in TXN_TYPES for d in entities[t] for line in d["Line"]}
    assert types == {
        "SalesItemLineDetail", "DiscountLineDetail", "SubTotalLineDetail", "DescriptionOnly",
        "AccountBasedExpenseLineDetail", "ItemBasedExpenseLineDetail", "JournalEntryLineDetail",
    }


def test_document_totals(entities):
    for t in SALES:
        for d in entities[t]:
            sales = sum((ln["Amount"] for ln in d["Line"] if ln["DetailType"] == "SalesItemLineDetail"), Decimal(0))
            disc = sum((ln["Amount"] for ln in d["Line"] if ln["DetailType"] == "DiscountLineDetail"), Decimal(0))
            [sub] = [ln["Amount"] for ln in d["Line"] if ln["DetailType"] == "SubTotalLineDetail"]
            assert sub == sales and d["TotalAmt"] == sales - disc, d["Id"]
            assert all("Id" not in ln and "LineNum" not in ln for ln in d["Line"]
                       if ln["DetailType"] in ("SubTotalLineDetail", "DiscountLineDetail"))
    for t in ("Bill", "Purchase"):
        for d in entities[t]:
            assert d["TotalAmt"] == sum((ln["Amount"] for ln in d["Line"]), Decimal(0))
    for d in entities["JournalEntry"]:
        debit = sum((ln["Amount"] for ln in d["Line"] if ln["JournalEntryLineDetail"]["PostingType"] == "Debit"), Decimal(0))
        credit = sum((ln["Amount"] for ln in d["Line"] if ln["JournalEntryLineDetail"]["PostingType"] == "Credit"), Decimal(0))
        assert debit == credit == d["TotalAmt"]


def test_voids_use_the_qbo_shape(entities):
    voided = [(t, d) for t in TXN_TYPES for d in entities[t] if d.get("PrivateNote") == "Voided"]
    assert sorted(t for t, _ in voided) == ["Invoice", "Purchase"]
    for _, d in voided:
        assert d["TotalAmt"] == 0 and d["SyncToken"] == "1"
        assert all(ln.get("Amount", Decimal(0)) == 0 for ln in d["Line"])
        assert all(ln[ln["DetailType"]].get("Qty", 0) == 0 for ln in d["Line"] if ln["DetailType"] in ln)


def test_inactive_account_is_present(entities):
    inactive = [a for a in entities["Account"] if not a["Active"]]
    assert [a["Name"] for a in inactive] == ["Website Hosting (deleted)"]


def test_budgets(entities):
    budgets = entities["Budget"]
    assert {b["BudgetType"] for b in budgets} == {"ProfitAndLoss"}
    assert {b["BudgetEntryType"] for b in budgets} == {"Monthly"}
    assert [b["Active"] for b in budgets].count(False) == 1
    lines = [r for b in budgets if b["Active"] for r in b["BudgetDetail"]]
    assert any("ClassRef" in r for r in lines) and any("ClassRef" not in r for r in lines)
    months = {r["BudgetDate"] for r in lines}
    assert min(months) == "2024-09-01" and max(months) == "2026-12-01" and len(months) == 28
    assert all(r["BudgetDate"].endswith("-01") for r in lines)


def test_storylines(files):
    data = demo_summary.load(files)
    gl = demo_summary.explode(data)
    s = demo_summary.storyline(data, gl)
    gm_delta = s["year2"]["gm_pct"] - s["year1"]["gm_pct"]
    assert Decimal("-3.5") <= gm_delta <= Decimal("-2.5")
    assert s["q4_share"][1] > 40 and s["q4_share"][2] > 40
    m = s["marketing"]
    early = sum((m[k][0] for k in range(1, 15)), Decimal(0)) / sum((m[k][1] for k in range(1, 15)), Decimal(0))
    late = sum((m[k][0] for k in range(15, 25)), Decimal(0)) / sum((m[k][1] for k in range(15, 25)), Decimal(0))
    assert Decimal("0.9") <= early <= Decimal("1.1") and late >= Decimal("1.2")
    assert all(k >= 15 or m[k][0] <= m[k][1] * Decimal("1.1") for k in range(1, 25))
    assert s["stable"] == {"Occupancy:Rent": [Decimal("8500.00")], "Software & Subscriptions": [Decimal("1240.00")]}
    assert s["payroll_je_months"] == 24
    assert s["year1"]["net_income"] > 0 and s["year2"]["net_income"] > 0


def test_expected_counts_match_generated(files, entities):
    data = demo_summary.load(files)
    counts = demo_summary.expected_counts(data, demo_summary.explode(data))
    assert counts["raw_entity (total)"] == sum(len(r) for r in entities.values())
    assert counts["dim_date"] == 1096  # 2024-01-01 .. 2026-12-31
    assert counts["vw_fact_gl"] < counts["fact_gl"]


def test_item_account_ref_on_most_sales_lines(entities):
    items = {i["Id"]: i for i in entities["Item"]}
    with_ref = without_ref = 0
    for t in SALES:
        for d in entities[t]:
            for ln in d["Line"]:
                if ln["DetailType"] != "SalesItemLineDetail":
                    continue
                detail = ln["SalesItemLineDetail"]
                if "ItemAccountRef" in detail:
                    with_ref += 1
                    assert detail["ItemAccountRef"]["value"] == items[detail["ItemRef"]["value"]]["IncomeAccountRef"]["value"]
                else:
                    without_ref += 1
                    assert d["TxnDate"] < "2024-10-01"  # only the first month exercises the fallback
    assert without_ref > 0 and with_ref > 20 * without_ref


def test_reference_prefers_item_account_ref():
    data = {
        "Account": [
            {"Id": "21", "Classification": "Revenue", "AccountType": "Income"},
            {"Id": "22", "Classification": "Revenue", "AccountType": "Income"},
        ],
        "Item": [{"Id": "1", "IncomeAccountRef": {"value": "21"}}],
        "Invoice": [{
            "Id": "101", "TxnDate": "2025-11-03", "Line": [
                {"Amount": Decimal("90.00"), "DetailType": "SalesItemLineDetail",
                 "SalesItemLineDetail": {"ItemRef": {"value": "1"}, "ItemAccountRef": {"value": "22"}}},
                {"Amount": Decimal("45.00"), "DetailType": "SalesItemLineDetail",
                 "SalesItemLineDetail": {"ItemRef": {"value": "1"}}},
            ],
        }],
    }
    gl = demo_summary.explode(data)
    assert [(g.account_id, g.amount_signed) for g in gl] == [("22", Decimal("90.00")), ("21", Decimal("45.00"))]


def test_vw_fact_gl_count_is_pnl_lines_only(files):
    data = demo_summary.load(files)
    gl = demo_summary.explode(data)
    counts = demo_summary.expected_counts(data, gl)
    classification = {a["Id"]: a["Classification"] for a in data["Account"]}
    balance_sheet = sum(1 for g in gl if classification[g.account_id] not in ("Revenue", "Expense"))
    voided = sum(1 for g in gl if g.is_voided)
    assert balance_sheet > 0
    assert counts["vw_fact_gl"] == counts["fact_gl"] - balance_sheet - voided
