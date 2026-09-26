"""Synthetic QBO-shaped demo company for Track C (spec 4 Phase 0; CLAUDE.md spec delta 3).

Writes one JSON array per QBO entity to ``demo_data/<Entity>.json``: the entity objects exactly
as a QBO v3 query returns them (minorversion 75 shapes), so ``load_demo.py`` lands them through
``qbo_sync.db.land_raw`` and dbt transforms them like real data.

Company: "Evergreen & Co. Gifts", a US corporate/wholesale/online gift-box seller.
Window: 24 full months, 2024-09-01 .. 2026-08-31 (fixed; no dependency on today's date).
Storylines (spec 4 Track C): Q4-heavy seasonality; gross margin about -3pp in year 2
(months 13-24); Marketing over budget from month 15 (Nov 2025); stable Rent and Software;
monthly payroll journal entry. Two voided transactions (QBO void shape: PrivateNote "Voided",
amounts and quantities zeroed). Sales lines carry ItemAccountRef as QBO returns it, except in the
first month (exercises the dbt fallback to the item's IncomeAccountRef).

Determinism: fixed seed, integer-only randomness, Decimal money, a hand-written JSON writer
(no float anywhere), LF line endings, ASCII output. A re-run gives byte-identical files.

Usage (from the repo root):  etl/.venv/Scripts/python etl/generate_synthetic.py [--out DIR]
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

SEED = 20240901
FIRST_MONTH = date(2024, 9, 1)
MONTHS = 24  # 2024-09 .. 2026-08
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "demo_data"

CENT = Decimal("0.01")
ONE = Decimal(1)
USD = {"value": "USD", "name": "United States Dollar"}
NON = {"value": "NON"}

# Revenue weight by calendar month: Q4 carries ~46 % of the year.
SEASON = {
    1: "0.60", 2: "0.65", 3: "0.75", 4: "0.80", 5: "0.85", 6: "0.80",
    7: "0.75", 8: "0.85", 9: "1.00", 10: "1.35", 11: "2.00", 12: "2.60",
}

# key, AcctNum, Name, parent key, AccountType, AccountSubType, Active
ACCOUNTS = [
    ("checking", "1000", "Checking", None, "Bank", "Checking", True),
    ("ar", "1100", "Accounts Receivable (A/R)", None, "Accounts Receivable", "AccountsReceivable", True),
    ("accum_depr", "1590", "Accumulated Depreciation", None, "Fixed Asset", "AccumulatedDepreciation", True),
    ("ap", "2000", "Accounts Payable (A/P)", None, "Accounts Payable", "AccountsPayable", True),
    ("credit_card", "2100", "Business Credit Card", None, "Credit Card", "CreditCard", True),
    ("payroll_liab", "2200", "Payroll Liabilities", None, "Other Current Liability", "PayrollTaxPayable", True),
    ("sales", "4000", "Sales", None, "Income", "SalesOfProductIncome", True),
    ("product_sales", "4010", "Product Sales", "sales", "Income", "SalesOfProductIncome", True),
    ("service_sales", "4020", "Custom Branding Services", "sales", "Income", "ServiceFeeIncome", True),
    ("discounts", "4900", "Discounts Given", None, "Income", "DiscountsRefundsGiven", True),
    ("cogs", "5000", "Cost of Goods Sold", None, "Cost of Goods Sold", "SuppliesMaterialsCogs", True),
    ("product_costs", "5010", "Product Costs", "cogs", "Cost of Goods Sold", "SuppliesMaterialsCogs", True),
    ("packaging", "5020", "Packaging Materials", "cogs", "Cost of Goods Sold", "SuppliesMaterialsCogs", True),
    ("freight", "5030", "Freight & Delivery", "cogs", "Cost of Goods Sold", "ShippingFreightDeliveryCos", True),
    ("payroll", "6000", "Payroll Expenses", None, "Expense", "PayrollExpenses", True),
    ("wages", "6010", "Wages & Salaries", "payroll", "Expense", "PayrollExpenses", True),
    ("payroll_taxes", "6020", "Payroll Taxes", "payroll", "Expense", "PayrollExpenses", True),
    ("marketing", "6100", "Marketing", None, "Expense", "AdvertisingPromotional", True),
    ("digital_ads", "6110", "Digital Advertising", "marketing", "Expense", "AdvertisingPromotional", True),
    ("trade_shows", "6120", "Trade Shows & Promotions", "marketing", "Expense", "AdvertisingPromotional", True),
    ("occupancy", "6200", "Occupancy", None, "Expense", "RentOrLeaseOfBuildings", True),
    ("rent", "6210", "Rent", "occupancy", "Expense", "RentOrLeaseOfBuildings", True),
    ("utilities", "6220", "Utilities", "occupancy", "Expense", "Utilities", True),
    ("software", "6300", "Software & Subscriptions", None, "Expense", "DuesSubscriptions", True),
    ("web_hosting", "6310", "Website Hosting (deleted)", None, "Expense", "OtherMiscellaneousServiceCost", False),
    ("insurance", "6400", "Insurance", None, "Expense", "Insurance", True),
    ("professional", "6500", "Professional Fees", None, "Expense", "LegalProfessionalFees", True),
    ("office_admin", "6600", "Office & Admin", None, "Expense", "OfficeGeneralAdministrativeExpenses", True),
    ("office_supplies", "6610", "Office Supplies", "office_admin", "Expense", "SuppliesMaterials", True),
    ("bank_fees", "6620", "Bank Fees", "office_admin", "Expense", "BankCharges", True),
    ("travel", "6700", "Travel", None, "Expense", "Travel", True),
    ("interest_earned", "7000", "Interest Earned", None, "Other Income", "InterestEarned", True),
    ("depreciation", "8000", "Depreciation", None, "Other Expense", "Depreciation", True),
]

CLASSIFICATION = {
    "Bank": "Asset", "Accounts Receivable": "Asset", "Fixed Asset": "Asset",
    "Accounts Payable": "Liability", "Credit Card": "Liability", "Other Current Liability": "Liability",
    "Income": "Revenue", "Other Income": "Revenue",
    "Cost of Goods Sold": "Expense", "Expense": "Expense", "Other Expense": "Expense",
}

# key, Name, Type, UnitPrice, PurchaseCost, income account key, expense account key
ITEMS = [
    ("classic_box", "Classic Gift Box", "NonInventory", "45.00", "21.50", "product_sales", "product_costs"),
    ("premium_box", "Premium Gift Box", "NonInventory", "95.00", "44.00", "product_sales", "product_costs"),
    ("executive_set", "Executive Gift Set", "NonInventory", "150.00", "71.00", "product_sales", "product_costs"),
    ("candle_set", "Seasonal Candle Set", "NonInventory", "32.00", "14.00", "product_sales", "product_costs"),
    ("snack_crate", "Gourmet Snack Crate", "NonInventory", "60.00", "28.50", "product_sales", "product_costs"),
    ("branding", "Custom Branding", "Service", "250.00", None, "service_sales", None),
    ("gift_wrap", "Gift Wrapping", "Service", "4.50", None, "service_sales", None),
    ("packaging_supplies", "Packaging Supplies", "NonInventory", None, "0.85", None, "packaging"),
]
PRODUCTS = ["classic_box", "premium_box", "executive_set", "candle_set", "snack_crate"]

CLASSES = [("corporate", "Corporate"), ("wholesale", "Wholesale"), ("online", "Online")]

CORPORATE = [
    "Northgate Advisory", "Bluewater Capital Partners", "Summit Ridge Consulting",
    "Ironwood Engineering", "Clearpath Logistics", "Brightline Health Group", "Harborstone Legal",
    "Cedar & Finch Architects", "Keystone Analytics", "Silverleaf Insurance Brokers",
    "Granite Peak Realty", "Orchard Lane Dental", "Meridian Tech Solutions", "Redwood Staffing",
    "Lakeshore Credit Union", "Pinecrest Property Management", "Vantage Point Marketing",
    "Stonebridge Wealth",
]
WHOLESALE = [
    "Maple Street Gifts", "Harborview Boutique", "The Paper Lantern", "Willow & Wick",
    "Corner Nook Mercantile", "Blue Door Home Goods", "Tidewater General Store", "Juniper Gift Co.",
    "Old Mill Market", "Sparrow Lane Shop", "Birch & Bramble", "Main Street Emporium",
    "Hollow Oak Trading", "Seaside Curiosities", "Copper Kettle Gifts", "Lighthouse Mercantile",
]
ONLINE = ["Web Store Sales", "Marketplace Sales"]
JOB = ("Northgate Advisory", "Holiday Program 2025")  # sub-customer (QBO job) of a corporate customer

# key, DisplayName
VENDORS = [
    ("artisan_box", "Artisan Box Company"), ("summit_gourmet", "Summit Gourmet Foods"),
    ("lumen_candle", "Lumen Candle Works"), ("pacific_crest", "Pacific Crest Wholesale"),
    ("prairie_craft", "Prairie Craft Imports"), ("evergreen_pack", "Evergreen Packaging Supply"),
    ("boxline", "BoxLine Packaging"), ("swift_parcel", "Swift Parcel Freight"),
    ("coastal_carriers", "Coastal Carriers"), ("harbor_point", "Harbor Point Properties"),
    ("city_power", "City Power & Water"), ("guardian", "Guardian Mutual Insurance"),
    ("bennett_cole", "Bennett & Cole CPAs"), ("rowan_legal", "Rowan Legal Group"),
    ("cloudledger", "CloudLedger Software"), ("inboxflow", "InboxFlow Email"),
    ("shippilot", "ShipPilot"), ("designhub", "DesignHub"), ("teamchat", "TeamChat Pro"),
    ("adreach", "AdReach Networks"), ("socialspark", "SocialSpark Ads"),
    ("gift_expo", "Regional Gift & Home Expo"), ("officemart", "OfficeMart Supply"),
    ("skyway", "SkyWay Airlines"), ("stayfine", "Stayfine Hotels"), ("first_harbor", "First Harbor Bank"),
]
PRODUCT_SUPPLIERS = ["artisan_box", "summit_gourmet", "lumen_candle", "pacific_crest", "prairie_craft"]
PACKAGING_SUPPLIERS = ["evergreen_pack", "boxline"]
FREIGHT_CARRIERS = ["swift_parcel", "coastal_carriers"]
# Software subscriptions: fixed monthly charges (stable storyline), total 1,240.00.
SOFTWARE = [
    ("cloudledger", "90.00"), ("inboxflow", "145.00"), ("shippilot", "499.00"),
    ("designhub", "79.00"), ("teamchat", "427.00"),
]
RENT = Decimal("8500.00")
INSURANCE = Decimal("915.00")
BOOKKEEPING = Decimal("1250.00")
DEPRECIATION = Decimal("1150.00")
DIGITAL_ADS_BUDGET = {10: Decimal(7500), 11: Decimal(7500), 12: Decimal(7500)}  # else 5000
TRADE_SHOW_MONTHS = {3: Decimal(4500), 6: Decimal(4500), 9: Decimal(4500), 10: Decimal(4500)}
MARKETING_OVERSPEND_FROM = 15  # month index (Nov 2025)
ITEM_ACCOUNT_REF_FROM_MONTH = 2  # sales lines carry ItemAccountRef from month 2 (Oct 2024) on


# ------------------------------------------------------------------ JSON writer (no float)


def to_json(obj: object) -> str:
    """Serialize dict/list/str/int/bool/None/Decimal to compact JSON; floats are rejected."""
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, Decimal):
        if not obj.is_finite():
            raise ValueError("non-finite Decimal")
        return format(obj, "f")
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, str):
        return json.dumps(obj)
    if isinstance(obj, dict):
        return "{" + ",".join(f"{json.dumps(k)}:{to_json(v)}" for k, v in obj.items()) + "}"
    if isinstance(obj, list):
        return "[" + ",".join(to_json(v) for v in obj) + "]"
    raise TypeError(f"cannot serialize {type(obj).__name__} (floats are not allowed)")


def dump_entities(entities: list[dict]) -> str:
    """One JSON array per file, one entity per line (diff-friendly), LF, trailing newline."""
    return "[\n" + ",\n".join(to_json(e) for e in entities) + "\n]\n"


# ------------------------------------------------------------------ helpers


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def whole(value: Decimal) -> int:
    return int(value.quantize(ONE, rounding=ROUND_HALF_UP))


def month_start(k: int) -> date:
    """Month k = 1..24 -> first day (k=1 is 2024-09-01)."""
    y, m = divmod(FIRST_MONTH.month - 1 + k - 1, 12)
    return date(FIRST_MONTH.year + y, m + 1, 1)


def month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def pacific_offset(d: date) -> str:
    """US Pacific UTC offset for MetaData timestamps (DST: 2nd Sunday of March .. 1st Sunday of Nov)."""
    march8 = date(d.year, 3, 8)
    nov1 = date(d.year, 11, 1)
    dst_start = march8 + timedelta(days=(6 - march8.weekday()) % 7)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)
    return "-07:00" if dst_start <= d < dst_end else "-08:00"


def stamp(d: date, minute: int) -> str:
    return f"{d.isoformat()}T{minute // 60:02d}:{minute % 60:02d}:00{pacific_offset(d)}"


def meta(created: date, minute: int, updated: date | None = None, updated_minute: int | None = None) -> dict:
    upd = updated or created
    return {
        "CreateTime": stamp(created, minute),
        "LastUpdatedTime": stamp(upd, minute if updated_minute is None else updated_minute),
    }


def ref(value: str, name: str | None = None) -> dict:
    return {"value": value} if name is None else {"value": value, "name": name}


@dataclass
class Account:
    id: str
    key: str
    name: str
    fqn: str
    account_type: str


@dataclass
class Item:
    id: str
    key: str
    name: str
    price: Decimal | None
    cost: Decimal | None
    income: str | None
    expense: str | None


@dataclass
class Party:
    id: str
    name: str
    channel: str | None = None


@dataclass
class Txn:
    """A generated transaction before Ids are assigned (sorted by date, then creation order)."""

    entity: str
    txn_date: date
    seq: int
    doc: dict
    doc_number_kind: str | None = None


# ------------------------------------------------------------------ generator


class Company:
    def __init__(self, seed: int = SEED) -> None:
        self.rng = random.Random(seed)
        self.seq = 0
        self.txns: list[Txn] = []
        self.accounts: dict[str, Account] = {}
        self.items: dict[str, Item] = {}
        self.classes: dict[str, Party] = {}
        self.customers: dict[str, Party] = {}
        self.vendors: dict[str, Party] = {}
        self.entities: dict[str, list[dict]] = {}
        self.revenue: dict[tuple[int, str], Decimal] = {}
        self.setup_day = FIRST_MONTH - timedelta(days=6)

    # -- random helpers (integers only; no float leaves the RNG)

    def per_mille(self, lo: int, hi: int) -> Decimal:
        return Decimal(self.rng.randint(lo, hi)) / Decimal(1000)

    def chance(self, percent: int) -> bool:
        return self.rng.randrange(100) < percent

    def day_in(self, k: int) -> date:
        start = month_start(k)
        return start.replace(day=self.rng.randint(1, month_end(start).day))

    def minute(self) -> int:
        return self.rng.randint(8 * 60, 18 * 60)

    def aref(self, key: str) -> dict:
        a = self.accounts[key]
        return ref(a.id, a.name)

    def add_txn(self, entity: str, txn_date: date, doc: dict, doc_number_kind: str | None = None) -> dict:
        self.seq += 1
        self.txns.append(Txn(entity, txn_date, self.seq, doc, doc_number_kind))
        return doc

    # -- name lists

    def build_lists(self) -> None:
        rows = []
        for n, (key, num, name, parent, atype, subtype, active) in enumerate(ACCOUNTS, start=1):
            parent_acc = self.accounts.get(parent) if parent else None
            fqn = f"{parent_acc.fqn}:{name}" if parent_acc else name
            acc = Account(str(n), key, name, fqn, atype)
            self.accounts[key] = acc
            row = {
                "Name": name,
                "SubAccount": parent_acc is not None,
            }
            if parent_acc:
                row["ParentRef"] = ref(parent_acc.id)
            row |= {
                "FullyQualifiedName": fqn,
                "Active": active,
                "Classification": CLASSIFICATION[atype],
                "AccountType": atype,
                "AccountSubType": subtype,
                "AcctNum": num,
                "CurrentBalance": Decimal(0),
                "CurrentBalanceWithSubAccounts": Decimal(0),
                "CurrencyRef": USD,
                "domain": "QBO",
                "sparse": False,
                "Id": acc.id,
                "SyncToken": "0" if active else "1",
                "MetaData": meta(self.setup_day, 9 * 60 + n, None if active else date(2025, 2, 3), 10 * 60),
            }
            rows.append(row)
        self.entities["Account"] = rows

        rows = []
        for n, (key, name, itype, price, cost, income, expense) in enumerate(ITEMS, start=1):
            item = Item(
                str(n), key, name,
                Decimal(price) if price else None, Decimal(cost) if cost else None, income, expense,
            )
            self.items[key] = item
            row: dict = {"Name": name, "Active": True, "FullyQualifiedName": name, "Taxable": False}
            if price:
                row |= {"Description": name, "UnitPrice": item.price, "IncomeAccountRef": self.aref(income)}
            row |= {"Type": itype}
            if cost:
                row |= {"PurchaseDesc": name, "PurchaseCost": item.cost, "ExpenseAccountRef": self.aref(expense)}
            row |= {
                "TrackQtyOnHand": False,
                "domain": "QBO",
                "sparse": False,
                "Id": item.id,
                "SyncToken": "0",
                "MetaData": meta(self.setup_day, 11 * 60 + n),
            }
            rows.append(row)
        self.entities["Item"] = rows

        rows = []
        for n, (key, name) in enumerate(CLASSES, start=1):
            cls = Party(f"50000000001000{n:05d}", name)
            self.classes[key] = cls
            rows.append({
                "Name": name, "SubClass": False, "FullyQualifiedName": name, "Active": True,
                "domain": "QBO", "sparse": False, "Id": cls.id, "SyncToken": "0",
                "MetaData": meta(self.setup_day, 12 * 60 + n),
            })
        self.entities["Class"] = rows

        # Customers and vendors share QBO's name-list Id sequence.
        name_id = 0
        rows = []
        for channel, names in (("corporate", CORPORATE), ("wholesale", WHOLESALE), ("online", ONLINE)):
            for name in names:
                name_id += 1
                party = Party(str(name_id), name, channel)
                self.customers[name] = party
                rows.append(self.customer_row(party, name, name, None, "1" if channel == "online" else "3"))
        parent = self.customers[JOB[0]]
        name_id += 1
        job = Party(str(name_id), JOB[1], "corporate")
        self.customers[":".join(JOB)] = job
        rows.append(self.customer_row(job, JOB[1], ":".join(JOB), parent.id, "3", created=date(2025, 9, 15)))
        self.entities["Customer"] = rows

        rows = []
        for key, name in VENDORS:
            name_id += 1
            vendor = Party(str(name_id), name)
            self.vendors[key] = vendor
            rows.append({
                "Balance": Decimal(0), "Vendor1099": key in ("bennett_cole", "rowan_legal"),
                "CurrencyRef": USD, "domain": "QBO", "sparse": False, "Id": vendor.id, "SyncToken": "0",
                "MetaData": meta(self.setup_day, 14 * 60 + name_id % 60),
                "CompanyName": name, "DisplayName": name, "PrintOnCheckName": name, "Active": True,
            })
        self.entities["Vendor"] = rows

    def customer_row(
        self, party: Party, display: str, fqn: str, parent_id: str | None, term: str, created: date | None = None
    ) -> dict:
        row: dict = {
            "Taxable": False, "Job": parent_id is not None, "BillWithParent": False,
            "Balance": Decimal(0), "BalanceWithJobs": Decimal(0), "CurrencyRef": USD,
            "PreferredDeliveryMethod": "Email", "IsProject": False, "domain": "QBO", "sparse": False,
            "Id": party.id, "SyncToken": "0",
            "MetaData": meta(created or self.setup_day, 13 * 60 + int(party.id) % 60),
            "FullyQualifiedName": fqn, "CompanyName": fqn.split(":")[0], "DisplayName": display,
            "PrintOnCheckName": fqn.split(":")[0], "Active": True, "SalesTermRef": ref(term),
        }
        if parent_id:
            row |= {"ParentRef": ref(parent_id), "Level": 1}
        return row

    # -- sales documents

    def sales_lines(
        self, k: int, lines: list[tuple[str, int, Decimal]], cls: Party | None, notes: list[str]
    ) -> tuple[list, Decimal]:
        out: list[dict] = []
        subtotal = Decimal(0)
        for n, (item_key, qty, price) in enumerate(lines, start=1):
            item = self.items[item_key]
            amount = money(Decimal(qty) * price)
            subtotal += amount
            detail: dict = {"ItemRef": ref(item.id, item.name)}
            # QBO returns ItemAccountRef (the account the line posted to) on sales lines. The
            # first month (Sep 2024) is written without it, so the dbt fallback to the item's
            # IncomeAccountRef is exercised by the demo data too. Rule by date, not by the RNG,
            # so the amounts of every other document stay unchanged.
            if k >= ITEM_ACCOUNT_REF_FROM_MONTH:
                detail["ItemAccountRef"] = self.aref(item.income)
            detail |= {"UnitPrice": price, "Qty": qty, "TaxCodeRef": NON}
            if cls is not None:
                detail["ClassRef"] = ref(cls.id, cls.name)
            out.append({
                "Id": str(n), "LineNum": n, "Description": item.name, "Amount": amount,
                "DetailType": "SalesItemLineDetail", "SalesItemLineDetail": detail,
            })
        for note in notes:
            n = len(out) + 1
            out.append({
                "Id": str(n), "LineNum": n, "Description": note,
                "DetailType": "DescriptionOnly", "DescriptionLineDetail": {},
            })
        # QBO returns a SubTotal line (no Id / LineNum) after the item lines.
        out.append({"Amount": subtotal, "DetailType": "SubTotalLineDetail", "SubTotalLineDetail": {}})
        return out, subtotal

    def discount_line(self, subtotal: Decimal, percent: int, cls: Party | None) -> tuple[dict, Decimal]:
        amount = money(subtotal * Decimal(percent) / Decimal(100))
        detail: dict = {
            "PercentBased": True,
            "DiscountPercent": percent,
            "DiscountAccountRef": self.aref("discounts"),
        }
        if cls is not None:
            detail["ClassRef"] = ref(cls.id, cls.name)
        return {"Amount": amount, "DetailType": "DiscountLineDetail", "DiscountLineDetail": detail}, amount

    def invoice(self, k: int) -> dict:
        corporate = self.chance(55)
        channel = "corporate" if corporate else "wholesale"
        customer = self.customers[self.rng.choice(CORPORATE if corporate else WHOLESALE)]
        txn_date = self.day_in(k)
        if customer.name == JOB[0] and date(2025, 10, 1) <= txn_date <= date(2025, 12, 31):
            customer = self.customers[":".join(JOB)]
        cls = self.classes[channel]
        lines: list[tuple[str, int, Decimal]] = []
        if corporate:
            for _ in range(self.rng.choice((1, 1, 2, 2, 2, 3))):
                lines.append((self.rng.choice(PRODUCTS), self.rng.randint(5, 40), None))
        else:
            for _ in range(self.rng.choice((2, 2, 3, 3, 4))):
                lines.append((self.rng.choice(PRODUCTS), self.rng.randint(6, 24), None))
        priced = []
        for item_key, qty, _ in lines:
            price = self.items[item_key].price
            if not corporate:
                price = money(price * Decimal("0.85"))  # wholesale price level
            priced.append((item_key, qty, price))
        units = sum(q for _, q, _ in priced)
        if corporate and self.chance(30):
            priced.append(("branding", 1, self.items["branding"].price))
        if corporate and self.chance(40):
            priced.append(("gift_wrap", units, self.items["gift_wrap"].price))
        notes = [self.rng.choice(("Thank you for your business!", "Deliver to reception, weekdays 9-5."))] if self.chance(25) else []
        line_json, subtotal = self.sales_lines(k, priced, cls, notes)
        total = subtotal
        if self.chance(12):
            disc, amount = self.discount_line(subtotal, self.rng.choice((5, 10)), cls)
            line_json.append(disc)
            total -= amount
        due = txn_date + timedelta(days=30)
        doc = {
            "AllowIPNPayment": False, "AllowOnlinePayment": False, "AllowOnlineCreditCardPayment": False,
            "AllowOnlineACHPayment": False, "domain": "QBO", "sparse": False, "Id": None, "SyncToken": "0",
            "MetaData": meta(txn_date, self.minute()), "CustomField": [], "DocNumber": None,
            "TxnDate": txn_date.isoformat(), "CurrencyRef": USD, "LinkedTxn": [], "Line": line_json,
            "TxnTaxDetail": {"TotalTax": Decimal(0)}, "CustomerRef": ref(customer.id, customer.name),
            "SalesTermRef": ref("3"), "DueDate": due.isoformat(), "TotalAmt": total,
            "ApplyTaxAfterDiscount": False, "PrintStatus": "NotSet", "EmailStatus": "EmailSent",
            "Balance": total if due > date(2026, 8, 31) else Decimal("0.00"),
        }
        self.book_revenue(k, channel, total)
        return self.add_txn("Invoice", txn_date, doc, "invoice")

    def sales_receipt(self, k: int) -> dict:
        customer = self.customers[ONLINE[0] if self.chance(75) else ONLINE[1]]
        txn_date = self.day_in(k)
        cls = self.classes["online"]
        priced = [
            (key, self.rng.randint(3, 25), self.items[key].price)
            for key in (self.rng.choice(PRODUCTS) for _ in range(self.rng.choice((2, 3, 3, 4))))
        ]
        # Online sales use transaction-level ClassRef (class per transaction), not line-level.
        line_json, subtotal = self.sales_lines(k, priced, None, [])
        total = subtotal
        if self.chance(10):
            disc, amount = self.discount_line(subtotal, 5, None)
            line_json.append(disc)
            total -= amount
        doc = {
            "domain": "QBO", "sparse": False, "Id": None, "SyncToken": "0",
            "MetaData": meta(txn_date, self.minute()), "CustomField": [], "DocNumber": None,
            "TxnDate": txn_date.isoformat(), "CurrencyRef": USD, "PrivateNote": "Daily web store batch",
            "Line": line_json, "TxnTaxDetail": {"TotalTax": Decimal(0)},
            "CustomerRef": ref(customer.id, customer.name), "ClassRef": ref(cls.id, cls.name),
            "TotalAmt": total, "ApplyTaxAfterDiscount": False, "PrintStatus": "NotSet",
            "EmailStatus": "NotSet", "Balance": Decimal("0.00"), "DepositToAccountRef": self.aref("checking"),
        }
        self.book_revenue(k, "online", total)
        return self.add_txn("SalesReceipt", txn_date, doc, "receipt")

    def credit_memo(self, k: int) -> dict:
        corporate = self.chance(50)
        channel = "corporate" if corporate else "wholesale"
        customer = self.customers[self.rng.choice(CORPORATE if corporate else WHOLESALE)]
        txn_date = self.day_in(k)
        cls = self.classes[channel]
        key = self.rng.choice(PRODUCTS)
        price = self.items[key].price if corporate else money(self.items[key].price * Decimal("0.85"))
        line_json, total = self.sales_lines(k, [(key, self.rng.randint(1, 6), price)], cls, [])
        doc = {
            "RemainingCredit": Decimal("0.00"), "domain": "QBO", "sparse": False, "Id": None,
            "SyncToken": "0", "MetaData": meta(txn_date, self.minute()), "CustomField": [],
            "DocNumber": None, "TxnDate": txn_date.isoformat(), "CurrencyRef": USD,
            "PrivateNote": "Return - damaged in transit", "Line": line_json,
            "TxnTaxDetail": {"TotalTax": Decimal(0)}, "CustomerRef": ref(customer.id, customer.name),
            "TotalAmt": total, "ApplyTaxAfterDiscount": False, "PrintStatus": "NotSet",
            "EmailStatus": "NotSet", "Balance": Decimal("0.00"),
        }
        self.book_revenue(k, channel, -total)
        return self.add_txn("CreditMemo", txn_date, doc, "memo")

    def book_revenue(self, k: int, channel: str, amount: Decimal) -> None:
        self.revenue[(k, channel)] = self.revenue.get((k, channel), Decimal(0)) + amount

    # -- expense documents

    def expense_line(self, n: int, account: str, amount: Decimal, desc: str, cls: Party | None = None) -> dict:
        detail: dict = {"AccountRef": self.aref(account), "BillableStatus": "NotBillable", "TaxCodeRef": NON}
        if cls is not None:
            detail["ClassRef"] = ref(cls.id, cls.name)
        return {
            "Id": str(n), "LineNum": n, "Description": desc, "Amount": amount,
            "DetailType": "AccountBasedExpenseLineDetail", "AccountBasedExpenseLineDetail": detail,
        }

    def item_line(self, n: int, item_key: str, qty: int, cls: Party | None = None) -> dict:
        item = self.items[item_key]
        detail: dict = {
            "ItemRef": ref(item.id, item.name), "UnitPrice": item.cost, "Qty": qty,
            "BillableStatus": "NotBillable", "TaxCodeRef": NON,
        }
        if cls is not None:
            detail["ClassRef"] = ref(cls.id, cls.name)
        return {
            "Id": str(n), "LineNum": n, "Description": item.name, "Amount": money(Decimal(qty) * item.cost),
            "DetailType": "ItemBasedExpenseLineDetail", "ItemBasedExpenseLineDetail": detail,
        }

    def bill(self, txn_date: date, vendor_key: str, lines: list[dict], note: str | None = None) -> dict:
        vendor = self.vendors[vendor_key]
        total = sum((ln["Amount"] for ln in lines), Decimal(0))
        due = txn_date + timedelta(days=30)
        doc: dict = {
            "DueDate": due.isoformat(), "Balance": total if due > date(2026, 8, 31) else Decimal("0.00"),
            "domain": "QBO", "sparse": False, "Id": None, "SyncToken": "0",
            "MetaData": meta(txn_date, self.minute()),
            "DocNumber": f"{vendor.name.split()[0][:3].upper()}-{self.rng.randint(10000, 99999)}",
            "TxnDate": txn_date.isoformat(), "CurrencyRef": USD,
        }
        if note:
            doc["PrivateNote"] = note
        doc |= {
            "Line": lines, "VendorRef": ref(vendor.id, vendor.name),
            "APAccountRef": self.aref("ap"), "TotalAmt": total,
        }
        return self.add_txn("Bill", txn_date, doc)

    def purchase(self, txn_date: date, vendor_key: str, pay: str, lines: list[dict]) -> dict:
        vendor = self.vendors[vendor_key]
        total = sum((ln["Amount"] for ln in lines), Decimal(0))
        account = {"CreditCard": "credit_card", "Check": "checking", "Cash": "checking"}[pay]
        doc: dict = {"AccountRef": self.aref(account), "PaymentType": pay}
        doc["EntityRef"] = {"value": vendor.id, "name": vendor.name, "type": "Vendor"}
        if pay == "CreditCard":
            doc["Credit"] = False
        doc |= {
            "TotalAmt": total, "PurchaseEx": {"any": []}, "domain": "QBO", "sparse": False, "Id": None,
            "SyncToken": "0", "MetaData": meta(txn_date, self.minute()), "CustomField": [],
        }
        if pay == "Check":
            doc["DocNumber"] = None
        doc |= {"TxnDate": txn_date.isoformat(), "CurrencyRef": USD, "Line": lines}
        return self.add_txn("Purchase", txn_date, doc, "check" if pay == "Check" else None)

    def journal(self, txn_date: date, note: str, doc_number: str, lines: list[tuple[str, str, Decimal, str]]) -> dict:
        out = []
        for n, (posting, account, amount, desc) in enumerate(lines):
            out.append({
                "Id": str(n), "Description": desc, "Amount": amount, "DetailType": "JournalEntryLineDetail",
                "JournalEntryLineDetail": {"PostingType": posting, "AccountRef": self.aref(account)},
            })
        debits = sum((a for p, _, a, _ in lines if p == "Debit"), Decimal(0))
        credits = sum((a for p, _, a, _ in lines if p == "Credit"), Decimal(0))
        if debits != credits:
            raise ValueError("journal entry must balance")
        doc = {
            "Adjustment": False, "TotalAmt": debits, "domain": "QBO", "sparse": False, "Id": None,
            "SyncToken": "0", "MetaData": meta(txn_date, 17 * 60 + self.rng.randint(0, 50)),
            "DocNumber": doc_number, "TxnDate": txn_date.isoformat(), "CurrencyRef": USD,
            "PrivateNote": note, "Line": out,
        }
        return self.add_txn("JournalEntry", txn_date, doc)

    @staticmethod
    def void(doc: dict, voided_on: date) -> None:
        """QBO void: the document stays, PrivateNote becomes "Voided", amounts and quantities are 0."""
        zero = Decimal("0.00")
        for line in doc["Line"]:
            if "Amount" in line:
                line["Amount"] = zero
            detail = line.get(line["DetailType"])
            if isinstance(detail, dict) and "Qty" in detail:
                detail["Qty"] = 0
        doc["TotalAmt"] = zero
        if "Balance" in doc:
            doc["Balance"] = zero
        doc["SyncToken"] = "1"
        doc["MetaData"]["LastUpdatedTime"] = stamp(voided_on, 10 * 60 + 15)
        doc["PrivateNote"] = "Voided"

    # -- monthly drivers

    def cogs_ratio(self, k: int) -> Decimal:
        """COGS / net revenue: ~52 % in year 1, drifting up ~3pp through year 2."""
        noise = Decimal(self.rng.randint(-3, 3)) / Decimal(1000)
        if k <= 12:
            return Decimal("0.520") + noise
        return Decimal("0.543") + Decimal(k - 13) * Decimal("0.0016") + noise

    def month(self, k: int) -> None:
        start = month_start(k)
        end = month_end(start)
        weight = Decimal(SEASON[start.month])
        growth = Decimal("1.00") if k <= 12 else Decimal("1.10")

        invoices = [self.invoice(k) for _ in range(whole(Decimal(44) * weight * growth))]
        for _ in range(whole(Decimal(16) * weight * growth)):
            self.sales_receipt(k)
        for _ in range(whole(Decimal("2.5") * weight * growth)):
            self.credit_memo(k)
        if k == 7:  # void one invoice in March 2025 (reversing its revenue)
            target = invoices[2]
            channel = "corporate" if any(
                ln.get("SalesItemLineDetail", {}).get("ClassRef", {}).get("name") == "Corporate"
                for ln in target["Line"]
            ) else "wholesale"
            self.book_revenue(k, channel, -target["TotalAmt"])
            self.void(target, date.fromisoformat(target["TxnDate"]) + timedelta(days=3))

        # COGS sized from this month's net revenue (margin storyline).
        ratio = self.cogs_ratio(k)
        total_revenue = sum((self.revenue.get((k, c), Decimal(0)) for c, _ in CLASSES), Decimal(0))
        for class_key, _ in CLASSES:
            target = self.revenue.get((k, class_key), Decimal(0)) * ratio * Decimal("0.88")
            count = max(1, whole(Decimal("1.2") + Decimal("1.3") * weight))
            for _ in range(count):
                lines, remaining = [], target / Decimal(count)
                picks = [self.rng.choice(PRODUCTS) for _ in range(self.rng.choice((1, 2, 3)))]
                for n, key in enumerate(picks, start=1):
                    share = remaining / Decimal(len(picks))
                    qty = max(1, whole(share / self.items[key].cost))
                    lines.append(self.item_line(n, key, qty, self.classes[class_key]))
                self.bill(self.day_in(k), self.rng.choice(PRODUCT_SUPPLIERS), lines)
        packaging = total_revenue * ratio * Decimal("0.06")
        for vendor in PACKAGING_SUPPLIERS:
            qty = max(1, whole(packaging / Decimal(2) / self.items["packaging_supplies"].cost))
            self.bill(self.day_in(k), vendor, [self.item_line(1, "packaging_supplies", qty)])
        freight = total_revenue * ratio * Decimal("0.06")
        count = 3 + whole(weight)
        freight_docs = []
        for n in range(count):
            amount = money(freight / Decimal(count) * self.per_mille(900, 1100))
            forced_check = k == 18 and n == 0  # the February 2026 void target
            pay = "Check" if forced_check or self.chance(40) else "CreditCard"
            line = self.expense_line(1, "freight", amount, "Outbound freight")
            freight_docs.append(self.purchase(self.day_in(k), self.rng.choice(FREIGHT_CARRIERS), pay, [line]))
        if k == 18:  # void one freight check in February 2026
            check = next(d for d in freight_docs if d["PaymentType"] == "Check")
            self.void(check, date.fromisoformat(check["TxnDate"]) + timedelta(days=2))

        # Fixed overheads.
        self.bill(start, "harbor_point", [self.expense_line(1, "rent", RENT, f"Rent {start:%B %Y}")])
        for n, (vendor, amount) in enumerate(SOFTWARE):
            line = self.expense_line(1, "software", Decimal(amount), "Monthly subscription")
            self.purchase(start.replace(day=5 + 2 * n), vendor, "CreditCard", [line])
        self.bill(start.replace(day=3), "guardian", [self.expense_line(1, "insurance", INSURANCE, "Business owner policy")])
        seasonal_power = Decimal("1.18") if start.month in (1, 2, 7, 8, 12) else Decimal("1.00")
        utilities = money(Decimal(560) * seasonal_power * self.per_mille(930, 1070))
        self.bill(start.replace(day=12), "city_power", [self.expense_line(1, "utilities", utilities, "Power and water")])
        self.bill(start.replace(day=25), "bennett_cole", [self.expense_line(1, "professional", BOOKKEEPING, "Monthly bookkeeping")])
        if start.month == 3:
            self.bill(start.replace(day=20), "bennett_cole", [self.expense_line(1, "professional", Decimal("3800.00"), "Annual tax preparation")])
        if self.chance(20):
            fee = money(Decimal(self.rng.randint(600, 2400)))
            self.bill(self.day_in(k), "rowan_legal", [self.expense_line(1, "professional", fee, "Contract review")])

        # Marketing: on budget through month 14, then 28-42 % over (storyline).
        over = self.per_mille(1280, 1420) if k >= MARKETING_OVERSPEND_FROM else self.per_mille(930, 1030)
        ads = DIGITAL_ADS_BUDGET.get(start.month, Decimal(5000)) * over
        for n in range(3):
            amount = money(ads / Decimal(3) * self.per_mille(950, 1050))
            vendor = "adreach" if n < 2 else "socialspark"
            line = self.expense_line(1, "digital_ads", amount, "Paid social and search campaigns")
            self.purchase(start.replace(day=8 + n * 9), vendor, "CreditCard", [line])
        if start.month in TRADE_SHOW_MONTHS:
            amount = money(TRADE_SHOW_MONTHS[start.month] * over)
            self.bill(start.replace(day=6), "gift_expo", [self.expense_line(1, "trade_shows", amount, "Booth and promotion package")])
        if k >= MARKETING_OVERSPEND_FROM and start.month == 12:
            line = self.expense_line(1, "trade_shows", Decimal("1850.00"), "Holiday pop-up promotion (unbudgeted)")
            self.bill(start.replace(day=2), "gift_expo", [line])

        # Small variable overheads.
        for _ in range(self.rng.choice((1, 2))):
            amount = money(Decimal(self.rng.randint(12000, 42000)) / Decimal(100))
            self.purchase(self.day_in(k), "officemart", "CreditCard", [self.expense_line(1, "office_supplies", amount, "Office supplies")])
        for _ in range(self.rng.choice((0, 1, 1, 2))):
            amount = money(Decimal(self.rng.randint(25000, 140000)) / Decimal(100))
            vendor = self.rng.choice(("skyway", "stayfine"))
            self.purchase(self.day_in(k), vendor, "CreditCard", [self.expense_line(1, "travel", amount, "Client visit")])
        bank_fee = money(Decimal(self.rng.randint(4500, 7500)) / Decimal(100))
        self.purchase(end, "first_harbor", "Cash", [self.expense_line(1, "bank_fees", bank_fee, "Monthly service charges")])

        # Payroll journal entry (monthly, storyline) and month-end adjustments.
        gross = Decimal(42000) if k <= 12 else Decimal(45500)
        if start.month in (11, 12):
            gross += Decimal(7000)  # seasonal staff
        gross = money(gross * self.per_mille(985, 1015))
        employer_tax = money(gross * Decimal("0.085"))
        withholding = money(gross * Decimal("0.21"))
        label = f"{start:%B %Y}"
        self.journal(end, f"Payroll - {label}", f"PR-{start:%Y-%m}", [
            ("Debit", "wages", gross, "Gross wages"),
            ("Debit", "payroll_taxes", employer_tax, "Employer payroll taxes"),
            ("Credit", "checking", gross - withholding, "Net pay"),
            ("Credit", "payroll_liab", withholding + employer_tax, "Withholding and employer taxes"),
        ])
        interest = money(Decimal(self.rng.randint(3500, 11000)) / Decimal(100))
        self.journal(end, f"Month-end adjustments - {label}", f"ADJ-{start:%Y-%m}", [
            ("Debit", "depreciation", DEPRECIATION, "Monthly depreciation"),
            ("Credit", "accum_depr", DEPRECIATION, "Monthly depreciation"),
            ("Debit", "checking", interest, "Interest credited by bank"),
            ("Credit", "interest_earned", interest, "Interest credited by bank"),
        ])

    # -- budgets

    def budget_lines(self, d: date, k_actual: int, factor: Decimal) -> list[dict]:
        """Budget for month `d`, planned from month `k_actual`'s revenue (x factor)."""
        rows: list[dict] = []

        def add(account: str, amount: Decimal, cls: str | None = None) -> None:
            row: dict = {"BudgetDate": d.isoformat(), "Amount": amount.quantize(ONE, rounding=ROUND_HALF_UP).quantize(CENT)}
            row["AccountRef"] = self.aref(account)
            if cls:
                c = self.classes[cls]
                row["ClassRef"] = ref(c.id, c.name)
            rows.append(row)

        for class_key, _ in CLASSES:
            plan = self.revenue.get((k_actual, class_key), Decimal(0)) * factor * self.per_mille(950, 1050)
            services = plan * Decimal("0.04") if class_key == "corporate" else Decimal(0)
            add("product_sales", plan - services, class_key)
            if services:
                add("service_sales", services, class_key)
            add("product_costs", plan * Decimal("0.52") * Decimal("0.88"), class_key)
        total = sum((self.revenue.get((k_actual, c), Decimal(0)) for c, _ in CLASSES), Decimal(0)) * factor
        add("packaging", total * Decimal("0.52") * Decimal("0.06"))
        add("freight", total * Decimal("0.52") * Decimal("0.06"))
        gross = (Decimal(42000) if d < date(2025, 9, 1) else Decimal(45000)) + (Decimal(7000) if d.month in (11, 12) else 0)
        add("wages", gross)
        add("payroll_taxes", gross * Decimal("0.085"))
        add("digital_ads", DIGITAL_ADS_BUDGET.get(d.month, Decimal(5000)))
        if d.month in TRADE_SHOW_MONTHS:
            add("trade_shows", TRADE_SHOW_MONTHS[d.month])
        add("rent", RENT)
        add("utilities", Decimal(600))
        add("software", sum((Decimal(a) for _, a in SOFTWARE), Decimal(0)))
        add("insurance", INSURANCE)
        add("professional", BOOKKEEPING + (Decimal(3800) if d.month == 3 else 0) + Decimal(300))
        add("office_supplies", Decimal(450))
        add("bank_fees", Decimal(60))
        add("travel", Decimal(900))
        add("interest_earned", Decimal(70))
        add("depreciation", DEPRECIATION)
        return rows

    def build_budgets(self) -> None:
        budgets = []

        def budget(bid: str, name: str, year: int, details: list[dict], active: bool, created: date) -> dict:
            return {
                "Name": name, "StartDate": f"{year}-01-01", "EndDate": f"{year}-12-31",
                "BudgetType": "ProfitAndLoss", "BudgetEntryType": "Monthly", "Active": active,
                "BudgetDetail": details, "domain": "QBO", "sparse": False, "Id": bid,
                "SyncToken": "0", "MetaData": meta(created, 15 * 60),
            }

        # FY2024: the company went live on QBO in Sep 2024, so only Sep-Dec carry amounts.
        fy24 = [row for k in range(1, 5) for row in self.budget_lines(month_start(k), k, Decimal("1.00"))]
        budgets.append(budget("1", "FY2024 Operating Budget", 2024, fy24, True, date(2024, 8, 28)))
        fy25 = [row for k in range(5, 17) for row in self.budget_lines(month_start(k), k, Decimal("1.00"))]
        draft = [row for k in range(5, 8) for row in self.budget_lines(month_start(k), k, Decimal("1.15"))]
        budgets.append(budget("2", "FY2025 Operating Budget (draft)", 2025, draft, False, date(2024, 11, 20)))
        budgets.append(budget("3", "FY2025 Operating Budget", 2025, fy25, True, date(2024, 12, 12)))
        # FY2026: Jan-Aug from this year's run rate, Sep-Dec from Sep-Dec 2025 x 1.08.
        fy26 = [row for k in range(17, 25) for row in self.budget_lines(month_start(k), k, Decimal("1.00"))]
        fy26 += [row for k in range(13, 17) for row in self.budget_lines(month_start(k + 12), k, Decimal("1.08"))]
        budgets.append(budget("4", "FY2026 Operating Budget", 2026, fy26, True, date(2025, 12, 10)))
        self.entities["Budget"] = budgets

    # -- assemble

    def assign_ids(self) -> None:
        counters = {"invoice": 1000, "receipt": 5000, "memo": 9000, "check": 2000}
        by_entity: dict[str, list[dict]] = {}
        for n, txn in enumerate(sorted(self.txns, key=lambda t: (t.txn_date, t.seq)), start=101):
            txn.doc["Id"] = str(n)
            if txn.doc_number_kind:
                counters[txn.doc_number_kind] += 1
                txn.doc["DocNumber"] = str(counters[txn.doc_number_kind])
            by_entity.setdefault(txn.entity, []).append(txn.doc)
        self.entities.update(by_entity)

    def generate(self) -> dict[str, list[dict]]:
        self.build_lists()
        for k in range(1, MONTHS + 1):
            self.month(k)
        self.build_budgets()
        self.assign_ids()
        return {name: self.entities[name] for name in sorted(self.entities)}


def generate(seed: int = SEED) -> dict[str, list[dict]]:
    """Return {entity name: [QBO objects]} for the demo company."""
    return Company(seed).generate()


def write(entities: dict[str, list[dict]], out_dir: Path) -> dict[str, str]:
    """Write <Entity>.json files; return {file name: sha256}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, rows in entities.items():
        data = dump_entities(rows).encode("ascii")
        path = out_dir / f"{name}.json"
        path.write_bytes(data)
        hashes[path.name] = hashlib.sha256(data).hexdigest()
    return hashes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder (default: demo_data/)")
    args = parser.parse_args(argv)
    entities = generate()
    hashes = write(entities, args.out)
    for name, rows in entities.items():
        print(f"{name:<14} {len(rows):>6}  sha256 {hashes[name + '.json'][:16]}")
    txns = sum(len(entities[n]) for n in ("Invoice", "SalesReceipt", "CreditMemo", "Bill", "Purchase", "JournalEntry"))
    print(f"{'transactions':<14} {txns:>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
