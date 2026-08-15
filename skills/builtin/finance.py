# -*- coding: utf-8 -*-
"""
Finance skill — lightweight, dependency-free financial lookups.

A deliberately thin skill: it delegates to the existing ``web_search`` action
(mode='price' for assets, a plain query for currency conversion). It exists to
demonstrate the "new capability in its own skill" pattern and is trivial to
extend with a real market-data API later.
"""

from skills.base import Skill, Tool


def _handle(args, context):
    from actions.web_search import web_search as web_search_action

    action = (args.get("action") or "price").lower()
    symbol = (args.get("symbol") or args.get("asset") or "").strip()
    amount = str(args.get("amount") or "").strip()
    from_cur = (args.get("from") or "").strip()
    to_cur = (args.get("to") or "").strip()

    if action == "convert":
        if not from_cur or not to_cur:
            return "I need both 'from' and 'to' currencies for a conversion."
        query = f"{amount + ' ' if amount else ''}{from_cur} to {to_cur} exchange rate"
        r = web_search_action(parameters={"query": query, "mode": "search"}, player=context.ui)
        return f"Currency conversion: {r}"

    if not symbol:
        return "I need a 'symbol' (e.g. 'AAPL', 'BTC', 'USD/EUR') to look up."

    query = f"{symbol} price"
    r = web_search_action(parameters={"query": query, "mode": "price"}, player=context.ui)
    return f"Price for {symbol}: {r}"


skill = Skill()
skill.name = "finance"
skill.display_name = "Finance"
skill.description = "Looks up asset prices (stocks, crypto) and currency conversions."
skill.permissions = ["network"]
skill.tools = [
    Tool(
        name="finance",
        description=(
            "Financial lookups. Use for stock or crypto prices, and currency conversion. "
            "action='price' with symbol=<ticker e.g. AAPL, BTC>. "
            "action='convert' with from=<currency> to=<currency> and optional amount."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "price | convert (default: price)"},
                "symbol": {"type": "STRING", "description": "Ticker symbol for price (e.g. AAPL, BTC, EUR)"},
                "from":   {"type": "STRING", "description": "Source currency for convert (e.g. USD)"},
                "to":     {"type": "STRING", "description": "Target currency for convert (e.g. EUR)"},
                "amount": {"type": "STRING", "description": "Optional amount to convert"},
            },
            "required": [],
        },
        handler=_handle,
    )
]
