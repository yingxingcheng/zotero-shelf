# Security and privacy

Zotero Shelf reads library data and downloads stored PDFs. Its Zotero HTTP client
rejects write methods; its WebDAV client permits GET, HEAD and PROPFIND only.
WebDAV requires HTTPS. Authenticated redirects to other hosts are refused.

Credentials live in user configuration files outside the checkout. On POSIX,
new credential files have mode 0600 and new configuration directories have mode
0700. Windows access depends on the user's normal account-directory ACLs.
Credentials are plaintext at rest; this release does not integrate an OS keyring.
Use a dedicated Zotero read key and your storage service's application password.

Status and routine error output omit secrets and HTTP response bodies. Downloaded
PDFs are stored in private cache directories. Archives are not extracted wholesale:
the selected PDF is streamed into a fixed cache filename, with size, PDF-header
and available checksum checks before replacing a cached file.

Do not include real configuration files, account data, PDF content or unredacted
HTTP traces in reports. If a credential has been shared accidentally, revoke it
at Zotero or the WebDAV provider and create a replacement.

Report vulnerabilities through the repository's private vulnerability-reporting
feature if enabled. Otherwise contact the maintainer through their GitHub profile
to arrange a private report before publishing sensitive details in an issue.
