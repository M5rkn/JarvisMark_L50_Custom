# -*- coding: utf-8 -*-
"""Browser skill — wraps the existing ``actions.browser_control`` module."""

from skills.base import Skill, Tool

_description = (
    "Controls any web browser. Use for: opening websites, searching the web, "
    "clicking elements, filling forms, scrolling, screenshots, navigation, any web-based task. "
    "CLOSING: to close a SINGLE tab, ALWAYS use action='close_tab' with tab_name=<title> "
    "or index=<number> — it closes only that tab and never the browser. Use action='close' "
    "to close one ENTIRE browser, or 'close_all' to close every browser window — only when "
    "the user explicitly asks to close the browser/window itself, never for a tab. "
    "Tab management: list_tabs (show open tabs), switch_tab (switch to a tab by name/index), "
    "close_tab (close a tab by name/index), tab_history (recent tabs), close_duplicates "
    "(close duplicate tabs), protect/unprotect (protect a tab from closing), "
    "current_tab (info about the active tab), open_in_new_tab (duplicate active tab). "
    "Workspaces: action='workspace' with command=save|restore|list|delete|close and name=<name>. "
    "Control mode: action='cdp_launch' restarts Chrome with remote debugging so JARVIS can "
    "manage the real browser's tabs. "
    "Simple open/search requests launch the user's own browser normally (their real profile "
    "and logged-in accounts); interactive actions (click, type, fill_form...) attach an "
    "automation browser. "
    "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
    "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
)

_parameters = {
    "type": "OBJECT",
    "properties": {
        "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all | list_tabs | switch_tab | tab_history | close_duplicates | protect | unprotect | current_tab | open_in_new_tab | workspace | cdp_launch | copy_link | scroll_to | click_first_result"},
        "browser":     {"type": "STRING", "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."},
        "tab_name":    {"type": "STRING", "description": "Tab name/title (or part of it) for switch_tab / close_tab / protect. Use only key words, e.g. 'Gmail', 'GitHub'."},
        "index":       {"type": "INTEGER", "description": "Tab number (1-based) for switch_tab / close_tab."},
        "command":     {"type": "STRING", "description": "Workspace command: save | restore | list | delete | close (workspace action)"},
        "name":        {"type": "STRING", "description": "Workspace name (workspace action)"},
        "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
        "query":       {"type": "STRING", "description": "Search query for search action"},
        "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
        "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
        "text":        {"type": "STRING", "description": "Text to click or type"},
        "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
        "direction":   {"type": "STRING", "description": "up | down for scroll"},
        "position":    {"type": "STRING", "description": "top | bottom for scroll_to action"},
        "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
        "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
        "path":        {"type": "STRING", "description": "Save path for screenshot"},
        "background":  {"type": "BOOLEAN", "description": "Open a new tab in the background without switching to it (new_tab action)"},
        "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
        "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
    },
    "required": ["action"],
}


def _handle(args, context):
    from actions.browser_control import browser_control
    return browser_control(parameters=args, player=context.ui)


skill = Skill()
skill.name = "browser"
skill.display_name = "Browser"
skill.description = "Controls any web browser — navigation, tabs, forms, screenshots."
skill.permissions = ["browser", "network"]
skill.tools = [Tool(name="browser_control", description=_description, parameters=_parameters, handler=_handle)]
