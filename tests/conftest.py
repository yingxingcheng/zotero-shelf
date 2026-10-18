import copy

import httpx2
import pytest

ARTICLE = {
    "key": "ABCD1234",
    "version": 1,
    "data": {
        "key": "ABCD1234",
        "version": 1,
        "itemType": "journalArticle",
        "title": "An example research article",
        "date": "2026",
        "creators": [{"creatorType": "author", "firstName": "Ada", "lastName": "Researcher"}],
        "DOI": "10.0000/example",
    },
}
NOTE = {
    "key": "NOTE1234",
    "version": 1,
    "data": {
        "key": "NOTE1234",
        "version": 1,
        "itemType": "note",
        "parentItem": "ABCD1234",
        "note": "<p>An example note.</p>",
    },
}
PDF_ITEM = {
    "key": "PDFD1234",
    "version": 1,
    "data": {
        "key": "PDFD1234",
        "version": 1,
        "itemType": "attachment",
        "parentItem": "ABCD1234",
        "filename": "example.pdf",
        "contentType": "application/pdf",
        "linkMode": "imported_file",
    },
}
SETTINGS = {
    "library_id": "123",
    "library_type": "user",
    "api_key": "TEST-KEY-NOT-A-REAL-CREDENTIAL",
}


@pytest.fixture
def settings():
    return copy.deepcopy(SETTINGS)


@pytest.fixture
def api_transport():
    requests = []

    def serve(request):
        requests.append(request)
        assert request.method == "GET"
        headers = {"Zotero-API-Version": "3", "Last-Modified-Version": "1", "Total-Results": "1"}
        path = request.url.path
        if request.url.params.get("format") == "bibtex":
            return httpx2.Response(
                200,
                headers={**headers, "Content-Type": "application/x-bibtex"},
                text="@article{example2026, title={An example research article}, year={2026}}",
            )
        if request.url.params.get("format") == "csljson":
            return httpx2.Response(
                200,
                headers=headers,
                json={"items": [{"id": "ABCD1234", "type": "article-journal", "title": "Example"}]},
            )
        if path.endswith("/fulltext"):
            result = {"content": "Indexed example PDF text", "indexedPages": 2, "totalPages": 2}
        elif path.endswith("/children"):
            result = [NOTE] if request.url.params.get("itemType") == "note" else [NOTE, PDF_ITEM]
        elif path.endswith("/collections"):
            result = [
                {
                    "key": "COLL1234",
                    "data": {
                        "key": "COLL1234",
                        "name": "Example collection",
                        "parentCollection": False,
                    },
                }
            ]
        elif path.endswith("/PDFD1234"):
            result = PDF_ITEM
        elif path.endswith("/ABCD1234"):
            result = ARTICLE
        elif request.url.params.get("itemType") == "attachment":
            result = [PDF_ITEM]
        elif request.url.params.get("itemType") == "note":
            result = [NOTE]
        else:
            result = [ARTICLE]
        return httpx2.Response(200, headers=headers, json=copy.deepcopy(result))

    return httpx2.MockTransport(serve), requests
