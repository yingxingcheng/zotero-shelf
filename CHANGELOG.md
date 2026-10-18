# Changelog

## 0.1.1

- Fix CSL JSON export from the live API: unwrap its `items` object to return a
  citation array in terminal output, JSON output and saved files.
- Correct the API test fixture and add regression checks for CSL JSON exports.
- Report statement and branch coverage in continuous integration.

## 0.1.0

- Installable Python package with `zshelf` and `zotero-shelf` commands.
- Human-readable terminal tables and JSON output for agents and scripts.
- Library search, collection browsing, item details, notes and indexed text.
- Citation export to BibTeX and CSL JSON.
- Guided, verified setup with hidden credential prompts.
- Personal-library WebDAV PDFs with Basic or Digest authentication.
- Verified local PDF caching and optional Poppler text extraction.
- Compatibility with the earlier `zotero-api` HPC configuration files.
- Offline tests and Linux/macOS/Windows continuous-integration jobs.
