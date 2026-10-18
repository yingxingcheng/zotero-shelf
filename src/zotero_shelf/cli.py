"""Zotero Shelf's human and machine interfaces."""

import argparse
import getpass
import json
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console

from . import __version__, config, webdav
from .display import render
from .errors import ShelfError
from .library import Library


def _limit(value):
    number = int(value)
    if not 1 <= number <= 100:
        raise argparse.ArgumentTypeError("Choose a number between 1 and 100.")
    return number


def _nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("Use a nonnegative number.")
    return number


def _positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Use a positive number.")
    return number


def _common(parser, *, root=False):
    default = None if root else argparse.SUPPRESS
    parser.add_argument("--config", type=Path, default=default, help="Library configuration file.")
    parser.add_argument(
        "--webdav-config", type=Path, default=default, help="WebDAV configuration file."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False if root else argparse.SUPPRESS,
        help="Print structured JSON for scripts and agents.",
    )


def parser():
    root = argparse.ArgumentParser(
        prog="zshelf",
        description="Your Zotero library and WebDAV PDFs, in the terminal.",
        epilog="Start with: zshelf setup   |   zshelf search 'your topic'",
    )
    root.add_argument("--version", action="version", version=f"Zotero Shelf {__version__}")
    _common(root, root=True)
    commands = root.add_subparsers(dest="command", required=True, title="commands")

    def command(name, help, **kwargs):
        sub = commands.add_parser(name, help=help, description=help, **kwargs)
        _common(sub)
        return sub

    setup = command("setup", "Connect your Zotero account using a hidden API-key prompt.")
    setup.add_argument("--library-type", choices=("user", "group"), default="user")
    command("status", "Show configuration paths and connection settings, without secrets.")
    command("check", "Verify access to your online library.")
    search = command("search", "Search your library, or list recently modified references.")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--collection", help="Limit results to a collection key.")
    search.add_argument(
        "--tag", action="append", help="Filter by tag; repeat to require multiple tags."
    )
    search.add_argument(
        "--everything", action="store_true", help="Include synced indexed content in search."
    )
    for name, help in [
        ("collections", "List collections."),
        ("children", "List an item's notes and attachments."),
        ("notes", "Read synced notes from the library or a particular reference."),
    ]:
        sub = command(name, help)
        if name == "children":
            sub.add_argument("key")
        elif name == "notes":
            sub.add_argument("key", nargs="?")
        sub.add_argument("--limit", type=_limit, default=20)
        sub.add_argument("--offset", type=_nonnegative, default=0)
    search.add_argument("--limit", type=_limit, default=20)
    search.add_argument("--offset", type=_nonnegative, default=0)
    command("show", "Read all metadata for an item.", aliases=["item"]).add_argument("key")
    command("fulltext", "Read Zotero's synced full-text index for an attachment.").add_argument(
        "key"
    )
    download = command("download", "Download a WebDAV PDF by attachment or reference key.")
    download.add_argument("key")
    download.add_argument("--output-dir", type=Path, help="PDF cache directory.")
    download.add_argument(
        "--force", action="store_true", help="Download even if a verified cached copy exists."
    )
    text = command("text", "Read text from a WebDAV PDF, or use Zotero's synced index.")
    text.add_argument("key")
    text.add_argument(
        "--indexed", action="store_true", help="Use synced indexed text instead of downloading."
    )
    text.add_argument("--first-page", type=_positive, help="First PDF page to read.")
    text.add_argument("--last-page", type=_positive, help="Last PDF page to read.")
    text.add_argument("-o", "--output", type=Path, help="Save text to a new file.")
    export = command("export", "Export selected references to BibTeX or CSL JSON.")
    export.add_argument("keys", nargs="+")
    export.add_argument("--format", choices=("bibtex", "csljson"), default="bibtex")
    export.add_argument("-o", "--output", type=Path, help="Save to a new file.")
    dav = command("webdav", "Set up and verify your WebDAV attachment storage.")
    dav_commands = dav.add_subparsers(dest="webdav_command", required=True)
    dav_setup = dav_commands.add_parser("setup", help="Connect an existing Zotero WebDAV folder.")
    _common(dav_setup)
    dav_setup.add_argument("--provider", choices=("nutstore", "generic"), default="nutstore")
    dav_setup.add_argument("--auth", choices=("basic", "digest"), default="basic")
    dav_check = dav_commands.add_parser(
        "check", help="Check the WebDAV folder and one PDF archive."
    )
    _common(dav_check)
    dav_check.add_argument("--key", help="A specific reference or PDF attachment key.")
    return root


def _prompt(label, default=""):
    suffix = f" [{default}]" if default else ""
    return input(label + suffix + ": ").strip() or default


def _setup(args):
    if args.json:
        raise ShelfError(
            "Setup is interactive. Omit --json and enter credentials at the terminal prompts."
        )
    if args.command == "setup":
        path = config.resolve_path("library", args.config, writing=True)
        current = config.read_json(config.resolve_path("library", args.config))
        identifier = _prompt("Numeric Zotero library ID", str(current.get("library_id", "")))
        if not identifier.isdigit() or int(identifier) < 1:
            raise ShelfError(
                "Enter the numeric library ID from https://www.zotero.org/settings/keys."
            )
        key = getpass.getpass(
            "Zotero API key (hidden; blank keeps an existing key): "
        ).strip() or current.get("api_key")
        if not key:
            raise ShelfError("An API key is required to connect a private library.")
        settings = {"library_id": identifier, "library_type": args.library_type, "api_key": key}
        with Library(settings) as library:
            library.check()
        config.private_json(path, settings)
        return {"connected": True, "config_file": str(path), "next": "zshelf search 'your topic'"}
    path = config.resolve_path("webdav", args.webdav_config, writing=True)
    current = config.read_json(config.resolve_path("webdav", args.webdav_config))
    default_url = current.get(
        "root_url", webdav.NUTSTORE_URL if args.provider == "nutstore" else ""
    )
    url = _prompt("WebDAV URL from Zotero's Sync settings", default_url)
    username = _prompt("WebDAV username / account email", current.get("username", ""))
    password = getpass.getpass(
        "WebDAV application password (hidden; blank keeps an existing password): "
    ).strip() or current.get("password")
    if not username or not password:
        raise ShelfError("A WebDAV username and application password are required.")
    settings = {
        "root_url": webdav.storage_url(url),
        "username": username,
        "password": password,
        "auth": args.auth,
    }
    with webdav.WebDAV(settings) as client:
        client.check()
    config.private_json(path, settings)
    return {"webdav_connected": True, "config_file": str(path), "next": "zshelf webdav check"}


def _pdf_text(path, first=None, last=None):
    executable = shutil.which("pdftotext")
    if not executable:
        raise ShelfError("Install Poppler's pdftotext, or use 'zshelf text KEY --indexed'.")
    if first and last and first > last:
        raise ShelfError("The first page must not exceed the last page.")
    command = [executable, "-layout", "-enc", "UTF-8"]
    for flag, number in [("-f", first), ("-l", last)]:
        if number:
            command.extend([flag, str(number)])
    command.extend([str(path), "-"])
    process = subprocess.run(
        command, capture_output=True, encoding="utf-8", errors="replace", timeout=120
    )
    if process.returncode:
        raise ShelfError("PDF text extraction failed. Check the PDF and requested page range.")
    if not process.stdout.strip():
        raise ShelfError("This PDF has no extractable text. A scanned document may need OCR.")
    return process.stdout


def _save_output(path, value):
    if not path:
        return value
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    try:
        with path.expanduser().open("x", encoding="utf-8") as output:
            output.write(text)
    except FileExistsError:
        raise ShelfError(
            "The output file already exists. Choose a new path to keep the existing file."
        ) from None
    return {"saved": str(path.expanduser().resolve())}


def execute(args):
    library_path = config.resolve_path("library", args.config)
    dav_path = config.resolve_path("webdav", args.webdav_config)
    if args.command == "status":
        return {"version": __version__, **config.status(library_path, dav_path)}
    if args.command == "setup" or (args.command == "webdav" and args.webdav_command == "setup"):
        return _setup(args)
    with Library(config.library_settings(library_path)) as library:
        if args.command == "check":
            return library.check()
        if args.command == "search":
            return library.search(
                args.query,
                limit=args.limit,
                offset=args.offset,
                collection=args.collection,
                tags=args.tag,
                everything=args.everything,
            )
        if args.command == "collections":
            return library.collections(args.limit, args.offset)
        if args.command in ("show", "item"):
            return library.item(args.key)
        if args.command == "children":
            return library.children(args.key, args.limit, args.offset)
        if args.command == "notes":
            return library.notes(args.key, args.limit, args.offset)
        if args.command == "fulltext":
            return library.fulltext(args.key)
        if args.command == "export":
            return _save_output(args.output, library.export(args.keys, args.format))
        if args.command == "webdav":
            attachment = library.pdf(args.key)
            with webdav.WebDAV(webdav.load_settings(dav_path)) as client:
                return client.check(attachment["data"]["key"])
        if args.command in ("download", "text"):
            attachment = library.pdf(args.key)
            if args.command == "text" and args.indexed:
                if args.first_page or args.last_page:
                    raise ShelfError(
                        "Page ranges apply to PDF extraction. Omit --indexed to use them."
                    )
                value = library.fulltext(attachment["data"]["key"])
                return _save_output(args.output, value.get("content", ""))
            folder = config.cache_dir() / f"{library.kind}-{library.identifier}" / "pdfs"
            if args.command == "download" and args.output_dir:
                folder = args.output_dir
            with webdav.WebDAV(webdav.load_settings(dav_path)) as client:
                result = client.download(attachment, folder, force=getattr(args, "force", False))
            if args.command == "download":
                return result
            return _save_output(
                args.output, _pdf_text(result["path"], args.first_page, args.last_page)
            )
    raise ShelfError("Unknown command.")


def _failure(message, json_mode, *, code=1):
    if json_mode:
        print(json.dumps({"error": {"message": message, "exit_code": code}}), file=sys.stderr)
    else:
        Console(stderr=True, highlight=False).print("Error: " + message, markup=False, style="red")
    return code


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = execute(args)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "export" and isinstance(result, list):
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            render(result)
        return 0
    except ShelfError as error:
        return _failure(str(error), args.json, code=2)
    except KeyboardInterrupt:
        return _failure("Interrupted.", args.json, code=130)
    except (OSError, ValueError):
        return _failure(
            "Cannot read a local file or configuration. Check its path and permissions.",
            args.json,
            code=2,
        )
    except Exception as error:
        # HTTP exceptions may contain URLs, headers, credentials, or private response bodies.
        status = getattr(getattr(error, "response", None), "status_code", None)
        suffix = f" (HTTP {status})" if status else ""
        return _failure(
            f"Request failed: {type(error).__name__}{suffix}. Check connectivity and access permissions.",
            args.json,
        )
