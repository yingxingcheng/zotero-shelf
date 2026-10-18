"""Read Zotero WebDAV PDF archives; never modify the remote service."""

import base64
import hashlib
import os
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urljoin, urlsplit, urlunsplit

from .config import private_json as save_private_json
from .config import read_json
from .errors import ShelfError

NUTSTORE_URL = "https://dav.jianguoyun.com/dav/"
MAX_BYTES = 512 * 1024 * 1024


class WebDAVError(ShelfError):
    """An error whose message contains neither credentials nor response bodies."""


def storage_url(value):
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    if any(ord(character) < 32 for character in value):
        raise WebDAVError("The WebDAV URL contains invalid control characters.")
    parts = urlsplit(value)
    try:
        parts.port
    except ValueError:
        raise WebDAVError("The WebDAV port is invalid.") from None
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise WebDAVError(
            "Use an HTTPS WebDAV URL without embedded credentials or query parameters."
        )
    path = parts.path.rstrip("/")
    if not path.endswith("/zotero"):
        path += "/zotero"
    return urlunsplit((parts.scheme, parts.netloc, path + "/", "", ""))


def load_settings(path):
    if not path.exists():
        raise WebDAVError("Run 'zshelf webdav setup' first.")
    settings = read_json(path, required=True)
    if not settings.get("username") or not settings.get("password"):
        raise WebDAVError("WebDAV credentials are incomplete. Run 'zshelf webdav setup' again.")
    if settings.get("auth", "basic") not in ("basic", "digest"):
        raise WebDAVError("Unsupported WebDAV authentication mode.")
    settings["root_url"] = storage_url(settings.get("root_url", ""))
    return settings


class WebDAV:
    def __init__(self, settings, transport=None):
        import httpx2

        self.root = storage_url(settings["root_url"])
        auth_type = httpx2.DigestAuth if settings.get("auth") == "digest" else httpx2.BasicAuth
        self.http = httpx2.Client(
            auth=auth_type(settings["username"], settings["password"]),
            timeout=httpx2.Timeout(90, connect=20),
            follow_redirects=False,
            headers={"User-Agent": "Zotero-Shelf/0.1.1"},
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.http.close()

    @contextmanager
    def request(self, method, suffix="", **kwargs):
        if method not in ("GET", "HEAD", "PROPFIND"):
            raise WebDAVError("This client permits only read requests.")
        if suffix and not re.fullmatch(r"[A-Z0-9]{8}\.zip", suffix):
            raise WebDAVError("Invalid attachment archive path.")
        url = self.root + suffix
        origin = urlsplit(self.root)
        for _ in range(5):
            with self.http.stream(method, url, **kwargs) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise WebDAVError("WebDAV returned a redirect without a destination.")
                    redirected = urlsplit(urljoin(url, location))
                    if (
                        (redirected.scheme, redirected.hostname, redirected.port or 443)
                        != (origin.scheme, origin.hostname, origin.port or 443)
                        or redirected.username
                        or redirected.password
                    ):
                        raise WebDAVError(
                            "WebDAV redirected to another server. Configure the final HTTPS endpoint instead."
                        )
                    url = redirected.geturl()
                    continue
                code = response.status_code
                if code in (401, 403):
                    raise WebDAVError(
                        f"WebDAV authentication/access failed (HTTP {code}). Check the WebDAV username and application password."
                    )
                if code == 404:
                    raise WebDAVError(
                        "WebDAV folder or attachment not found (HTTP 404). Check the URL and desktop file sync."
                    )
                if code >= 400:
                    raise WebDAVError(
                        f"WebDAV request failed (HTTP {code}). Retry later or check the service."
                    )
                yield response
                return
        raise WebDAVError("WebDAV returned too many redirects.")

    def check(self, key=None):
        body = b'<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>'
        with self.request(
            "PROPFIND", content=body, headers={"Depth": "0", "Content-Type": "application/xml"}
        ) as response:
            if response.status_code != 207:
                raise WebDAVError("The URL did not return a WebDAV directory. Check the endpoint.")
            blocks = []
            size = 0
            for chunk in response.iter_bytes(65536):
                size += len(chunk)
                if size > 1024 * 1024:
                    raise WebDAVError("The WebDAV directory response is too large.")
                blocks.append(chunk)
            content = b"".join(blocks)
            if len(content) > 1024 * 1024 or ET.fromstring(content).tag != "{DAV:}multistatus":
                raise WebDAVError("The server returned an unexpected WebDAV directory response.")
        result = {"webdav_connected": True, "mode": "read-only"}
        if key:
            check_key(key)
            with self.request("HEAD", key + ".zip") as response:
                if response.status_code != 200:
                    raise WebDAVError("The attachment archive is not accessible.")
                result["attachment_archive_accessible"] = True
                result["attachment_key"] = key
        return result

    def download(self, attachment, cache_root, *, force=False):
        data = attachment.get("data", attachment)
        key = data.get("key")
        check_key(key)
        if not is_stored_pdf(attachment):
            raise WebDAVError(
                "Choose a stored PDF attachment; linked files and web links are not WebDAV files."
            )
        Path(cache_root).expanduser().mkdir(mode=0o700, parents=True, exist_ok=True)
        directory = Path(cache_root).expanduser() / key
        if directory.is_symlink():
            raise WebDAVError("The attachment cache directory must not be a symbolic link.")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = directory / "attachment.pdf"
        expected = str(data.get("md5") or "").lower()
        if expected and not re.fullmatch(r"[a-f0-9]{32}", expected):
            raise WebDAVError("Zotero returned an invalid attachment checksum.")
        if (
            not force
            and expected
            and target.is_file()
            and not target.is_symlink()
            and md5_file(target) == expected
        ):
            return {
                "attachment_key": key,
                "path": str(target.resolve()),
                "cached": True,
                "md5_verified": True,
            }
        with tempfile.TemporaryDirectory(prefix=".download-", dir=directory) as temporary:
            archive = Path(temporary) / "attachment.zip"
            with self.request("GET", key + ".zip") as response, archive.open("wb") as output:
                if response.status_code != 200:
                    raise WebDAVError("The server did not return a complete attachment archive.")
                size = 0
                for chunk in response.iter_bytes(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise WebDAVError(
                            "The attachment archive exceeds the 512 MiB download limit."
                        )
                    output.write(chunk)
            extracted = Path(temporary) / "attachment.pdf"
            extract_pdf(archive, data.get("filename", ""), extracted)
            actual = md5_file(extracted)
            if expected and expected != actual:
                raise WebDAVError(
                    "Attachment checksum differs from Zotero metadata. Finish desktop sync and retry."
                )
            os.chmod(extracted, 0o600)
            os.replace(extracted, target)
        result = {
            "attachment_key": key,
            "path": str(target.resolve()),
            "cached": False,
            "filename": data.get("filename"),
            "md5": actual,
            "md5_verified": bool(expected),
        }
        save_private_json(directory / "download.json", result)
        return result


def check_key(key):
    if not isinstance(key, str) or not re.fullmatch(r"[A-Z0-9]{8}", key):
        raise WebDAVError("Use a valid eight-character attachment key.")


def is_stored_pdf(item):
    data = item.get("data", item)
    return (
        data.get("itemType") == "attachment"
        and data.get("linkMode") in ("imported_file", "imported_url")
        and (
            data.get("contentType") == "application/pdf"
            or str(data.get("filename", "")).lower().endswith(".pdf")
        )
    )


def md5_file(path):
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_pdf(archive, filename, destination):
    with zipfile.ZipFile(archive) as zipped:
        entries = []
        for info in zipped.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if name.endswith("%ZB64"):
                name = base64.b64decode(name[:-5], validate=True).decode("utf-8")
            path = PurePosixPath(name.replace("\\", "/"))
            if path.is_absolute() or PureWindowsPath(name).drive or ".." in path.parts:
                raise WebDAVError("The attachment archive contains an unsafe filename.")
            if not path.name.startswith(".zotero"):
                entries.append((info, str(path)))
        matching = [entry for entry in entries if entry[1] == filename]
        if not matching:
            matching = [entry for entry in entries if entry[1].lower().endswith(".pdf")]
        if not matching and len(entries) == 1:
            matching = entries
        if len(matching) != 1:
            raise WebDAVError("The archive does not contain one identifiable PDF attachment.")
        info, _ = matching[0]
        if info.file_size > MAX_BYTES:
            raise WebDAVError("The PDF exceeds the 512 MiB size limit.")
        with zipped.open(info) as source, destination.open("xb") as output:
            size = 0
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise WebDAVError("The PDF exceeds the size limit.")
                if size == len(chunk) and b"%PDF-" not in chunk[:1024]:
                    raise WebDAVError("The downloaded attachment is not a PDF.")
                output.write(chunk)
            if size == 0:
                raise WebDAVError("The PDF is empty.")
