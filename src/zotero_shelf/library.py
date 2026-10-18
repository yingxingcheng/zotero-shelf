"""A small read-only service layer over Pyzotero."""

import re

import httpx2
from pyzotero import zotero

from .errors import ShelfError


def item_key(value):
    value = str(value).upper()
    if not re.fullmatch(r"[A-Z0-9]{8}", value):
        raise ShelfError("Use an eight-character Zotero item or collection key.")
    return value


def _read_request(request):
    if request.method not in ("GET", "HEAD"):
        raise ShelfError("Zotero Shelf permits only read requests.")


class Library:
    def __init__(self, settings, transport=None):
        self.kind = settings["library_type"]
        self.identifier = settings["library_id"]
        self.http = httpx2.Client(
            timeout=45, event_hooks={"request": [_read_request]}, transport=transport
        )
        self.api = zotero.Zotero(
            self.identifier, self.kind, settings.get("api_key"), client=self.http
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.http.close()

    def check(self):
        records = self.api.top(limit=1)
        return {
            "connected": True,
            "library_id": self.identifier,
            "library_type": self.kind,
            "sample_item_key": records[0]["key"] if records else None,
            "mode": "read-only",
        }

    def search(self, query="", *, limit=20, offset=0, collection=None, tags=None, everything=False):
        params = {"limit": limit, "start": offset, "sort": "dateModified", "direction": "desc"}
        if query:
            params.update(q=query, qmode="everything" if everything else "titleCreatorYear")
        if tags:
            params["tag"] = tags
        records = (
            self.api.collection_items_top(item_key(collection), **params)
            if collection
            else self.api.top(**params)
        )
        return page(records, offset, limit)

    def collections(self, limit=100, offset=0):
        return page(self.api.collections(limit=limit, start=offset), offset, limit, "collections")

    def item(self, key):
        return self.api.item(item_key(key))

    def children(self, key, limit=100, offset=0):
        return page(self.api.children(item_key(key), limit=limit, start=offset), offset, limit)

    def notes(self, key=None, limit=20, offset=0):
        params = {"itemType": "note", "limit": limit, "start": offset}
        records = self.api.children(item_key(key), **params) if key else self.api.items(**params)
        return page(records, offset, limit)

    def fulltext(self, key):
        return self.api.fulltext_item(item_key(key))

    def pdf(self, key=None):
        from .webdav import is_stored_pdf

        if self.kind != "user":
            raise ShelfError("WebDAV file sync is available for personal libraries.")
        if key:
            record = self.item(key)
            if record.get("data", {}).get("itemType") == "attachment":
                if is_stored_pdf(record):
                    return record
                raise ShelfError(
                    "Choose a stored PDF attachment, rather than a linked file or URL."
                )
            records = self.api.everything(self.api.children(item_key(key), limit=100))
        else:
            records = self.api.items(
                itemType="attachment", limit=100, sort="dateModified", direction="desc"
            )
        pdfs = [record for record in records if is_stored_pdf(record)]
        if not pdfs:
            raise ShelfError(
                "No stored PDF found in these items. Use 'zshelf children KEY' to find an attachment."
            )
        if key and len(pdfs) > 1:
            raise ShelfError(
                "Several PDFs are attached. Use 'zshelf children KEY' and choose an attachment key."
            )
        return pdfs[0]

    def export(self, keys, format="bibtex"):
        if not 1 <= len(keys) <= 50:
            raise ShelfError("Export between 1 and 50 item keys at a time.")
        result = self.api.items(
            itemKey=",".join(item_key(key) for key in keys), format=format, limit=len(keys)
        )
        if format == "bibtex":
            import bibtexparser

            return bibtexparser.dumps(result)
        return result


def page(records, offset, limit, name="items"):
    return {
        name: records,
        "count": len(records),
        "offset": offset,
        "next_offset": offset + len(records) if len(records) == limit else None,
    }
