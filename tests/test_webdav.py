"""Offline checks for Zotero archives, authentication boundaries and local cache integrity."""

import base64
import hashlib
import io
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

import httpx2

from zotero_shelf import webdav as dav

PDF = b"%PDF-1.7\nA small offline PDF-shaped attachment fixture.\n%%EOF\n"
NAME = "paper \u03b1.pdf"
KEY = "ABCD1234"
SETTINGS = {
    "root_url": "https://dav.example.test/dav/zotero/",
    "username": "test@example.test",
    "password": "DUMMY-APPLICATION-PASSWORD",
}
XML = b'<d:multistatus xmlns:d="DAV:"><d:response><d:href>/dav/zotero/</d:href></d:response></d:multistatus>'


def archive(name=NAME, content=PDF):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        zipped.writestr(".zotero-ft-cache", "indexed text")
        zipped.writestr(name, content)
    return output.getvalue()


def item(checksum=None):
    return {
        "data": {
            "key": KEY,
            "itemType": "attachment",
            "linkMode": "imported_file",
            "filename": NAME,
            "contentType": "application/pdf",
            "md5": checksum or hashlib.md5(PDF, usedforsecurity=False).hexdigest(),
        }
    }


class WebDAVTests(unittest.TestCase):
    def make_client(self, payload):
        self.requests = []

        def serve(request):
            self.requests.append(request)
            self.assertIn(request.method, ("GET", "HEAD", "PROPFIND"))
            self.assertEqual(request.url.host, "dav.example.test")
            self.assertEqual(
                request.headers["Authorization"],
                "Basic "
                + base64.b64encode(
                    f"{SETTINGS['username']}:{SETTINGS['password']}".encode()
                ).decode(),
            )
            if request.method == "PROPFIND":
                self.assertEqual(request.headers["Depth"], "0")
                return httpx2.Response(207, content=XML)
            return httpx2.Response(200, content=payload if request.method == "GET" else b"")

        return dav.WebDAV(SETTINGS, transport=httpx2.MockTransport(serve))

    def test_encoded_unicode_pdf_and_checksum_cache(self):
        encoded = base64.b64encode(NAME.encode()).decode() + "%ZB64"
        with (
            tempfile.TemporaryDirectory() as directory,
            self.make_client(archive(encoded)) as client,
        ):
            self.assertTrue(client.check(KEY)["attachment_archive_accessible"])
            result = client.download(item(), Path(directory))
            self.assertEqual(Path(result["path"]).read_bytes(), PDF)
            self.assertTrue(result["md5_verified"])
            if __import__("os").name != "nt":
                self.assertEqual(stat.S_IMODE(Path(result["path"]).stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(Path(result["path"]).parent.stat().st_mode), 0o700)
            count = len(self.requests)
            self.assertTrue(client.download(item(), Path(directory))["cached"])
            self.assertEqual(len(self.requests), count)

    def test_hash_mismatch_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory, self.make_client(archive()) as client:
            target = Path(directory) / KEY / "attachment.pdf"
            target.parent.mkdir()
            target.write_bytes(b"existing cached copy")
            with self.assertRaisesRegex(dav.WebDAVError, "checksum differs"):
                client.download(item("0" * 32), Path(directory))
            self.assertEqual(target.read_bytes(), b"existing cached copy")
            self.assertFalse(list(target.parent.glob(".download-*")))

    def test_zip_traversal_is_not_written(self):
        encoded = base64.b64encode(b"../outside.pdf").decode() + "%ZB64"
        with (
            tempfile.TemporaryDirectory() as directory,
            self.make_client(archive(encoded)) as client,
        ):
            with self.assertRaisesRegex(dav.WebDAVError, "unsafe filename"):
                client.download(item(), Path(directory))
            self.assertEqual(list(Path(directory).rglob("*.pdf")), [])

    def test_non_pdf_response_is_rejected(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            self.make_client(archive(content=b"<html>login</html>")) as client,
        ):
            with self.assertRaisesRegex(dav.WebDAVError, "not a PDF"):
                client.download(item(), Path(directory))

    def test_cross_host_redirect_never_receives_credentials(self):
        requests = []

        def serve(request):
            requests.append(request)
            return httpx2.Response(302, headers={"Location": "https://another.example.test/steal"})

        with dav.WebDAV(SETTINGS, transport=httpx2.MockTransport(serve)) as client:
            with self.assertRaisesRegex(dav.WebDAVError, "another server"):
                client.check()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.host, "dav.example.test")

    def test_remote_writes_are_rejected_before_network(self):
        with self.make_client(archive()) as client:
            with self.assertRaisesRegex(dav.WebDAVError, "only read"):
                with client.request("PUT"):
                    pass
            self.assertEqual(self.requests, [])

    def test_url_normalization(self):
        self.assertEqual(
            dav.storage_url("dav.jianguoyun.com/dav"), "https://dav.jianguoyun.com/dav/zotero/"
        )
        self.assertEqual(dav.storage_url(SETTINGS["root_url"]), SETTINGS["root_url"])
        for url in [
            "http://dav.example.test/",
            "https://user:password@dav.example.test/",
            "https://dav.example.test/?secret=value",
        ]:
            with self.assertRaises(dav.WebDAVError):
                dav.storage_url(url)


if __name__ == "__main__":
    unittest.main()
