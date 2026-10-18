import io
import zipfile

import httpx2
import pytest

from zotero_shelf import webdav

SETTINGS = {
    "root_url": "https://dav.example.test/dav/zotero/",
    "username": "example",
    "password": "DUMMY",
}


def test_default_https_port_redirect_is_same_origin():
    requests = []

    def serve(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx2.Response(
                307, headers={"Location": "https://dav.example.test:443/storage/zotero/"}
            )
        return httpx2.Response(207, content=b'<d:multistatus xmlns:d="DAV:"/>')

    with webdav.WebDAV(SETTINGS, httpx2.MockTransport(serve)) as client:
        assert client.check()["webdav_connected"]
    assert len(requests) == 2


def test_download_size_limit_preserves_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(webdav, "MAX_BYTES", 8)
    item = {
        "data": {
            "key": "ABCD1234",
            "itemType": "attachment",
            "linkMode": "imported_file",
            "contentType": "application/pdf",
            "filename": "example.pdf",
        }
    }
    target = tmp_path / "ABCD1234/attachment.pdf"
    target.parent.mkdir()
    target.write_bytes(b"previous cache")
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, content=b"x" * 100))
    with webdav.WebDAV(SETTINGS, transport) as client:
        with pytest.raises(webdav.WebDAVError, match="limit"):
            client.download(item, tmp_path)
    assert target.read_bytes() == b"previous cache"


@pytest.mark.parametrize("name", ["C:/outside.pdf", "/outside.pdf", "..\\outside.pdf"])
def test_unsafe_archive_paths_are_rejected(tmp_path, name):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as zipped:
        zipped.writestr(name, b"%PDF-1.7\nexample")
    archive = tmp_path / "archive.zip"
    archive.write_bytes(stream.getvalue())
    with pytest.raises(webdav.WebDAVError, match="unsafe filename"):
        webdav.extract_pdf(archive, "outside.pdf", tmp_path / "output.pdf")
    assert not (tmp_path / "output.pdf").exists()


def test_archive_path_cannot_escape_webdav_folder():
    requests = []
    transport = httpx2.MockTransport(lambda request: requests.append(request))
    with webdav.WebDAV(SETTINGS, transport) as client:
        with pytest.raises(webdav.WebDAVError, match="archive path"):
            with client.request("GET", "../unrelated.zip"):
                pass
    assert requests == []
