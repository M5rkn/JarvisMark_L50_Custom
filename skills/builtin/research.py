# -*- coding: utf-8 -*-
"""Research skill — wraps web_search, flight_finder and weather_report."""

from skills.base import Skill, Tool


def _web_search(args, context):
    from actions.web_search import web_search as web_search_action
    r = web_search_action(parameters=args, player=context.ui)
    # Mirror results into the on-screen content panel (previously inline in main.py).
    if r and not str(r).startswith("No results") and not str(r).startswith("Search failed"):
        mode = args.get("mode", "search")
        query = args.get("query") or ", ".join(args.get("items", []))
        label = f"{str(mode).upper()} — {query[:38]}" if query else str(mode).upper()
        try:
            context.ui.show_content(label, r)
        except Exception:
            pass
    return r


def _flight_finder(args, context):
    from actions.flight_finder import flight_finder
    return flight_finder(parameters=args, player=context.ui)


def _weather(args, context):
    from actions.weather_report import weather_action
    return weather_action(parameters=args, player=context.ui)


skill = Skill()
skill.name = "research"
skill.display_name = "Research"
skill.description = "Searches the web, finds flights and reports the weather."
skill.permissions = ["network", "browser"]
skill.tools = [
    Tool(
        name="web_search",
        description=(
            "Searches the web. Use for ANY question about current facts, events, prices, "
            "or topics — always prefer this over guessing. "
            "Modes: 'search' (default), 'news' (latest headlines on a topic), "
            "'research' (deep comprehensive answer), 'price' (product cost lookup), "
            "'compare' (side-by-side comparison of items)."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query or topic"},
                "mode":   {"type": "STRING", "description": "search | news | research | price | compare"},
                "items":  {"type": "ARRAY",  "items": {"type": "STRING"}, "description": "Items to compare (compare mode)"},
                "aspect": {"type": "STRING", "description": "Comparison aspect: price | specs | reviews | features"},
            },
            "required": ["query"],
        },
        handler=_web_search,
    ),
    Tool(
        name="flight_finder",
        description="Searches Google Flights and speaks the best options.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"],
        },
        handler=_flight_finder,
    ),
    Tool(
        name="weather_report",
        description="Gives the weather report to user",
        parameters={
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"],
        },
        handler=_weather,
    ),
]
