"""Read-only MCP server (stdio) exposing Empower Personal Dashboard data.

All tools are GET-equivalent fetches of data the Empower web dashboard
already shows. Nothing here writes, transfers, or modifies anything.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import EmpowerClient, EmpowerError, SessionExpiredError, SETUP_HINT

mcp = FastMCP("empower")

_client: EmpowerClient | None = None


def _get_client() -> EmpowerClient:
    global _client
    if _client is None:
        client = EmpowerClient()
        if not client.load_session():
            raise SessionExpiredError(
                "No Empower session found. Run `empower-mcp setup` in a terminal "
                "first (it will walk through email/password + 2FA), then retry."
            )
        _client = client
    return _client


def _epoch_ms_to_iso(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return dt.datetime.fromtimestamp(value / 1000, tz=dt.timezone.utc).isoformat()


def _validate_date(name: str, value: str) -> str:
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}")
    return value


def _format_transaction(txn: dict[str, Any], categories: dict[int, str]) -> dict[str, Any]:
    amount = txn.get("amount")
    if amount is not None and txn.get("isCredit") is False and amount > 0:
        amount = -amount
    return {
        "date": txn.get("transactionDate"),
        "merchant": txn.get("merchant") or txn.get("description"),
        "description": txn.get("description"),
        "amount": amount,
        "category": categories.get(txn.get("categoryId"), None),
        "account": txn.get("accountName"),
        "account_id": txn.get("userAccountId"),
        "status": txn.get("status"),
    }


@mcp.tool()
def get_accounts() -> dict[str, Any]:
    """List all linked financial accounts from Empower Personal Dashboard.

    Returns each account's name, institution, type, current balance, and
    last-synced timestamp, plus portfolio-level totals. Read-only.
    """
    sp_data = _get_client().get_accounts()
    accounts = []
    for acct in sp_data.get("accounts") or []:
        if acct.get("closedDate"):
            continue
        accounts.append(
            {
                "account_id": acct.get("userAccountId"),
                "name": acct.get("name") or acct.get("originalName"),
                "institution": acct.get("firmName"),
                "type": acct.get("accountType"),
                "type_group": acct.get("accountTypeGroup"),
                "balance": acct.get("balance"),
                "currency": acct.get("currency", "USD"),
                "last_synced": _epoch_ms_to_iso(acct.get("lastRefreshed")),
            }
        )
    return {
        "accounts": accounts,
        "totals": {
            "net_worth": sp_data.get("networth"),
            "assets": sp_data.get("assets"),
            "liabilities": sp_data.get("liabilities"),
            "cash": sp_data.get("cashAccountsTotal"),
            "investments": sp_data.get("investmentAccountsTotal"),
            "credit_cards": sp_data.get("creditCardAccountsTotal"),
            "loans": sp_data.get("loanAccountsTotal"),
            "mortgages": sp_data.get("mortgageAccountsTotal"),
        },
    }


@mcp.tool()
def get_transactions(
    start_date: str,
    end_date: str,
    account_id: int | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """Fetch transactions between start_date and end_date (YYYY-MM-DD, inclusive).

    Each transaction includes date, merchant, amount (negative = money out),
    category, account, and pending/posted status. Optionally filter by
    account_id (from get_accounts) and/or category name (case-insensitive).
    Read-only.
    """
    _validate_date("start_date", start_date)
    _validate_date("end_date", end_date)
    client = _get_client()
    categories = client.get_categories()
    txns = client.get_transactions(start_date, end_date)
    formatted = [_format_transaction(t, categories) for t in txns]
    if account_id is not None:
        formatted = [t for t in formatted if t["account_id"] == account_id]
    if category:
        wanted = category.strip().lower()
        formatted = [t for t in formatted if (t["category"] or "").lower() == wanted]
    return {"count": len(formatted), "transactions": formatted}


@mcp.tool()
def get_net_worth(as_of_date: str | None = None) -> dict[str, Any]:
    """Get current net worth (assets, liabilities, breakdown by account group).

    If as_of_date (YYYY-MM-DD) is given, also returns daily historical net
    worth snapshots from that date through today, when the history endpoint
    is available. Read-only.
    """
    client = _get_client()
    sp_data = client.get_accounts()
    result: dict[str, Any] = {
        "net_worth": sp_data.get("networth"),
        "assets": sp_data.get("assets"),
        "liabilities": sp_data.get("liabilities"),
        "breakdown": {
            "cash": sp_data.get("cashAccountsTotal"),
            "investments": sp_data.get("investmentAccountsTotal"),
            "credit_cards": sp_data.get("creditCardAccountsTotal"),
            "loans": sp_data.get("loanAccountsTotal"),
            "mortgages": sp_data.get("mortgageAccountsTotal"),
            "other_assets": sp_data.get("otherAssetAccountsTotal"),
            "other_liabilities": sp_data.get("otherLiabilitiesAccountsTotal"),
        },
    }
    if as_of_date:
        _validate_date("as_of_date", as_of_date)
        today = dt.date.today().isoformat()
        try:
            history = client.get_networth_history(as_of_date, today)
            result["history"] = [
                {
                    "date": h.get("date"),
                    "net_worth": h.get("networth"),
                    "assets": h.get("totalAssets") or h.get("assets"),
                    "liabilities": h.get("totalLiabilities") or h.get("liabilities"),
                }
                for h in history
            ]
        except SessionExpiredError:
            raise
        except EmpowerError as exc:
            result["history"] = None
            result["history_note"] = (
                f"Historical snapshots unavailable from the history endpoint: {exc}"
            )
    return result


@mcp.tool()
def get_holdings(account_id: int | None = None) -> dict[str, Any]:
    """List investment positions: symbol, description, quantity, price, value,
    and cost basis when Empower provides it. Optionally filter to one
    account_id (from get_accounts).

    Note: this only covers what Empower's own dashboard shows — options
    positions will NOT include strike, expiration, or Greeks. Read-only.
    """
    client = _get_client()
    holdings = client.get_holdings([account_id] if account_id is not None else None)
    formatted = []
    for h in holdings:
        formatted.append(
            {
                "symbol": h.get("ticker"),
                "description": h.get("description"),
                "quantity": h.get("quantity"),
                "price": h.get("price"),
                "value": h.get("value"),
                "cost_basis": h.get("costBasis"),
                "one_day_change": h.get("oneDayValueChange"),
                "account": h.get("accountName"),
                "account_id": h.get("userAccountId"),
                "holding_type": h.get("holdingType"),
            }
        )
    return {"count": len(formatted), "holdings": formatted}


@mcp.tool()
def get_cash_flow(start_date: str, end_date: str) -> dict[str, Any]:
    """Summarize income vs. spending between start_date and end_date
    (YYYY-MM-DD, inclusive), broken down by category.

    Computed from the transaction feed using Empower's own income/spending
    flags, so it matches the dashboard's cash-flow view. Transfers between
    your own accounts are excluded. Read-only.
    """
    _validate_date("start_date", start_date)
    _validate_date("end_date", end_date)
    client = _get_client()
    categories = client.get_categories()
    txns = client.get_transactions(start_date, end_date)

    total_income = 0.0
    total_spending = 0.0
    income_by_category: dict[str, float] = defaultdict(float)
    spending_by_category: dict[str, float] = defaultdict(float)

    for txn in txns:
        amount = txn.get("amount") or 0.0
        name = categories.get(txn.get("categoryId"), "Uncategorized") or "Uncategorized"
        if txn.get("isIncome"):
            total_income += amount
            income_by_category[name] += amount
        elif txn.get("isSpending"):
            total_spending += amount
            spending_by_category[name] += amount

    def _sorted(d: dict[str, float]) -> dict[str, float]:
        return {k: round(v, 2) for k, v in sorted(d.items(), key=lambda kv: -kv[1])}

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_income": round(total_income, 2),
        "total_spending": round(total_spending, 2),
        "net_cash_flow": round(total_income - total_spending, 2),
        "income_by_category": _sorted(income_by_category),
        "spending_by_category": _sorted(spending_by_category),
    }


def run() -> None:
    mcp.run(transport="stdio")
