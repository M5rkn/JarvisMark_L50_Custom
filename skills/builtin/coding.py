# -*- coding: utf-8 -*-
"""Coding skill — wraps ``actions.code_helper`` and ``actions.dev_agent``."""

from skills.base import Skill, Tool


def _code_helper(args, context):
    from actions.code_helper import code_helper
    return code_helper(parameters=args, player=context.ui, speak=context.speak)


def _dev_agent(args, context):
    from actions.dev_agent import dev_agent
    return dev_agent(parameters=args, player=context.ui, speak=context.speak)


skill = Skill()
skill.name = "coding"
skill.display_name = "Coding"
skill.description = "Writes, edits, explains, runs and builds code — from a single file to a full project."
skill.permissions = ["filesystem", "execution"]
skill.tools = [
    Tool(
        name="code_helper",
        description="Writes, edits, explains, runs, or builds code files.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"],
        },
        handler=_code_helper,
    ),
    Tool(
        name="dev_agent",
        description="Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"],
        },
        handler=_dev_agent,
    ),
]
