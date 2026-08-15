# -*- coding: utf-8 -*-
"""Files skill — wraps ``actions.file_controller`` and ``actions.file_processor``."""

from skills.base import Skill, Tool


def _file_controller(args, context):
    from actions.file_controller import file_controller
    return file_controller(parameters=args, player=context.ui)


def _file_processor(args, context):
    from actions.file_processor import file_processor
    # If no path given and a file is currently dropped on the UI, use it.
    if not args.get("file_path") and getattr(context.ui, "current_file", None):
        args["file_path"] = context.ui.current_file
    return file_processor(parameters=args, player=context.ui, speak=context.speak)


skill = Skill()
skill.name = "files"
skill.display_name = "Files"
skill.description = "Manages files and folders, and processes uploaded documents (PDF, images, docs, media, archives)."
skill.permissions = ["filesystem"]
skill.tools = [
    Tool(
        name="file_controller",
        description="Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"],
        },
        handler=_file_controller,
    ),
    Tool(
        name="file_processor",
        description=(
            "Processes any file that the user has uploaded or dropped onto the interface. "
            "Use this when the user refers to an uploaded file and wants an action on it. "
            "Supports: images (describe/ocr/resize/compress/convert), "
            "PDFs (summarize/extract_text/to_word), "
            "Word docs & text files (summarize/fix/reformat/translate), "
            "CSV/Excel (analyze/stats/filter/sort/convert), "
            "JSON/XML (validate/format/analyze), "
            "code files (explain/review/fix/optimize/run/document/test), "
            "audio (transcribe/trim/convert/info), "
            "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
            "archives (list/extract), "
            "presentations (summarize/extract_text). "
            "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
            "If the user's command is ambiguous, pick the most logical action for that file type."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "file_path": {"type": "STRING", "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."},
                "action": {"type": "STRING", "description": "What to do with the file (image: describe|ocr|resize|compress|convert|info; pdf: summarize|extract_text|to_word|info; docx/txt: summarize|fix|reformat|translate_hint|word_count|to_bullet; csv/excel: analyze|stats|filter|sort|convert|info; json: validate|format|analyze|to_csv; code: explain|review|fix|optimize|run|document|test; audio: transcribe|trim|convert|info; video: trim|extract_audio|extract_frame|compress|transcribe|info|convert; archive: list|extract; pptx: summarize|extract_text|analyze)"},
                "instruction": {"type": "STRING", "description": "Free-form instruction if action doesn't cover it."},
                "format": {"type": "STRING", "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"},
                "width":     {"type": "INTEGER", "description": "Target width for image resize"},
                "height":    {"type": "INTEGER", "description": "Target height for image resize"},
                "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
                "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
                "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
                "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
                "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
                "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
                "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
                "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
                "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
                "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
                "destination": {"type": "STRING", "description": "Output folder for archive extract"},
            },
            "required": [],
        },
        handler=_file_processor,
    ),
]
