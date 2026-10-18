"""Readable terminal output; unmodified JSON remains available for agents."""

import re
from html.parser import HTMLParser

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text


def clean(value):
    return "".join(c for c in str(value) if c.isprintable() or c in "\n\t")


class _NoteText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "div", "br", "li", "h1", "h2", "h3"):
            self.parts.append("\n")


def note_text(html):
    parser = _NoteText()
    parser.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()


def authors(data):
    names = [
        creator.get("lastName") or creator.get("name", "") for creator in data.get("creators", [])
    ]
    return ", ".join(names[:2]) + (" et al." if len(names) > 2 else "")


def render(value, console=None):
    console = console or Console(highlight=False)
    if isinstance(value, str):
        console.print(Text(clean(value)), end="" if value.endswith("\n") else "\n")
        return
    if "items" in value or "collections" in value:
        collections = "collections" in value
        records = value.get("items", value.get("collections", []))
        table = Table(box=box.SIMPLE, header_style="bold cyan", expand=True)
        table.add_column("Key", no_wrap=True, style="cyan")
        if collections:
            table.add_column("Collection")
            table.add_column("Parent", no_wrap=True)
        else:
            table.add_column("Year", no_wrap=True)
            table.add_column("Title / note", ratio=3)
            table.add_column("Authors", ratio=1)
        for record in records:
            data = record.get("data", record)
            key = str(record.get("key", data.get("key", "")))
            if collections:
                row = [key, data.get("name", ""), data.get("parentCollection") or "—"]
            else:
                date = re.search(r"\d{4}", str(data.get("date", "")))
                title = (
                    data.get("title") or note_text(data.get("note", "")) or data.get("filename", "")
                )
                row = [key, date.group() if date else "—", title, authors(data)]
            table.add_row(*(Text(clean(cell)) for cell in row))
        if records:
            console.print(table)
        else:
            console.print("No matching records.")
        console.print(f"{len(records)} result(s)", style="dim")
        if value.get("next_offset") is not None:
            console.print(f"Next page: --offset {value['next_offset']}", style="dim")
        return
    if "data" in value:
        data = value["data"]
        console.rule(Text(clean(data.get("title") or "Zotero item")), style="cyan")
        for key, entry in data.items():
            if not entry:
                continue
            if key == "note":
                entry = note_text(entry)
            if isinstance(entry, (list, dict)):
                import json

                entry = json.dumps(entry, ensure_ascii=False)
            console.print(Text(f"{key}: ", style="bold") + Text(clean(entry)))
        return
    if "content" in value:
        console.print(Text(clean(value["content"])))
        return
    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column(style="bold")
    table.add_column()
    for key, entry in value.items():
        table.add_row(Text(key.replace("_", " ")), Text(clean(entry)))
    console.print(table)
