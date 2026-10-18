import httpx2
import pytest

from zotero_shelf.errors import ShelfError
from zotero_shelf.library import Library, item_key


def test_search_and_pagination(settings, api_transport):
    transport, requests = api_transport
    with Library(settings, transport) as library:
        result = library.search("example", limit=1, offset=4, tags=["physics"], everything=True)
    assert result["next_offset"] == 5
    assert result["items"][0]["key"] == "ABCD1234"
    params = requests[-1].url.params
    assert params["q"] == "example"
    assert params["qmode"] == "everything"
    assert params["tag"] == "physics"
    assert params["start"] == "4"


def test_metadata_notes_and_pdf_resolution(settings, api_transport):
    transport, _ = api_transport
    with Library(settings, transport) as library:
        assert library.check()["connected"]
        assert library.item("abcd1234")["data"]["DOI"] == "10.0000/example"
        assert library.notes("ABCD1234")["items"][0]["key"] == "NOTE1234"
        assert library.collections()["collections"][0]["key"] == "COLL1234"
        assert library.pdf("ABCD1234")["key"] == "PDFD1234"
        assert library.pdf()["key"] == "PDFD1234"
        assert library.fulltext("PDFD1234")["content"].startswith("Indexed")


def test_exports(settings, api_transport):
    transport, _ = api_transport
    with Library(settings, transport) as library:
        assert "@article{example2026" in library.export(["ABCD1234"])
        assert library.export(["ABCD1234"], "csljson")[0]["type"] == "article-journal"
        with pytest.raises(ShelfError, match="1 and 50"):
            library.export([])


def test_api_write_is_blocked_before_transport(settings):
    requests = []

    def serve(request):
        requests.append(request)
        return httpx2.Response(200)

    with Library(settings, httpx2.MockTransport(serve)) as library:
        with pytest.raises(ShelfError, match="only read"):
            library.http.post("https://api.zotero.org/users/123/items", json={})
    assert requests == []


@pytest.mark.parametrize("wrapped", [True, False])
def test_csl_export_normalizes_api_response(settings, wrapped):
    citations = [{"id": "ABCD1234", "type": "article-journal", "title": "Example"}]
    payload = {"items": citations} if wrapped else citations
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, json=payload))
    with Library(settings, transport) as library:
        assert library.export(["ABCD1234"], "csljson") == citations


@pytest.mark.parametrize("payload", [{"unexpected": []}, {"items": "bad"}, ["not a citation"]])
def test_csl_export_rejects_unexpected_response(settings, payload):
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, json=payload))
    with Library(settings, transport) as library:
        with pytest.raises(ShelfError, match="unexpected CSL JSON"):
            library.export(["ABCD1234"], "csljson")


@pytest.mark.parametrize("key", ["../../x", "TOO-LONG-KEY", "", "é1234567"])
def test_invalid_keys_are_rejected(key):
    with pytest.raises(ShelfError):
        item_key(key)
