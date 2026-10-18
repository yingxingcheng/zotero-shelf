# Contributing

Issues and focused pull requests are welcome. Describe the command, the expected
behavior, and a redacted error message. Synthetic records are ideal for reproducing
problems; please keep API keys, passwords, private library records, and PDF files
out of issues and pull requests.

Use Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
pytest
ruff check .
ruff format --check .
python -m build
twine check dist/*
```

Tests use HTTP mock transports and generated archive fixtures. They must run
without accounts, secrets, external network access, or changes to a real library.
Cover behavior at service boundaries: API query parameters and pagination,
credential handling, download validation, error output, and cache integrity.

The command-line interface and service layer expose read operations only.
Preserve that boundary in additions. Keep machine-specific installation paths,
logs, caches and connection reports outside the repository.
