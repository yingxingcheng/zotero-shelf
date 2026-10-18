"""Configuration stays outside the checkout and is never included in distributions."""

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

from .errors import ShelfError


def config_dir():
    if os.environ.get("XDG_CONFIG_HOME"):
        return Path(os.environ["XDG_CONFIG_HOME"]) / "zotero-shelf"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "zotero-shelf"
    return Path.home() / ".config/zotero-shelf"


def cache_dir():
    if os.environ.get("XDG_CACHE_HOME"):
        return Path(os.environ["XDG_CACHE_HOME"]) / "zotero-shelf"
    if sys.platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
            / "zotero-shelf/cache"
        )
    return Path.home() / ".cache/zotero-shelf"


def resolve_path(kind, explicit=None, *, writing=False):
    filename = "config.json" if kind == "library" else "webdav.json"
    if explicit:
        return Path(explicit).expanduser()
    normal = config_dir() / filename
    # Read the earlier HPC client's configuration without copying its secrets.
    legacy = Path.home() / ".config/zotero-api" / filename
    if not writing and not normal.exists() and legacy.exists():
        return legacy
    return normal


def read_json(path, *, required=False):
    if not path.exists():
        if required:
            raise ShelfError("Configuration is missing. Run 'zshelf setup' first.")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ShelfError(
            "Cannot read the configuration. Check its JSON format and permissions."
        ) from None
    if not isinstance(value, dict):
        raise ShelfError("Configuration must be a JSON object.")
    return value


def private_json(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".settings-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, ensure_ascii=False)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def library_settings(path):
    value = read_json(path)
    for field, variable in [
        ("library_id", "ZOTERO_LIBRARY_ID"),
        ("library_type", "ZOTERO_LIBRARY_TYPE"),
        ("api_key", "ZOTERO_API_KEY"),
    ]:
        if os.environ.get(variable):
            value[field] = os.environ[variable]
    identifier = str(value.get("library_id", ""))
    kind = value.get("library_type", "user")
    if not identifier.isdigit() or int(identifier) < 1 or kind not in ("user", "group"):
        raise ShelfError("Set a numeric library ID using 'zshelf setup' or ZOTERO_LIBRARY_ID.")
    key = value.get("api_key")
    if key is not None and (not isinstance(key, str) or any(c in key for c in "\r\n")):
        raise ShelfError("The API key has an invalid format. Run 'zshelf setup' again.")
    return {"library_id": identifier, "library_type": kind, "api_key": key}


def status(library_path, webdav_path):
    library = read_json(library_path)
    return {
        "library_id": os.environ.get("ZOTERO_LIBRARY_ID", library.get("library_id")),
        "library_type": os.environ.get("ZOTERO_LIBRARY_TYPE", library.get("library_type", "user")),
        "api_key_configured": bool(os.environ.get("ZOTERO_API_KEY") or library.get("api_key")),
        "webdav_configured": webdav_path.exists(),
        "library_config": str(library_path),
        "webdav_config": str(webdav_path),
        "mode": "read-only",
    }


def private_permissions(path):
    return os.name == "nt" or not (stat.S_IMODE(Path(path).stat().st_mode) & 0o077)
