# Contributing

Thanks for your interest in topomask. Bug reports, detection gaps and pull requests are welcome.

## Ground rules

- Use only documentation values in code, tests, issues and examples: IPv4 from RFC 5737 (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`), IPv6 from RFC 3849 (`2001:db8::/32`), domains from RFC 2606 (`example.com`, `example.net`, `.test`). Never paste real logs.
- Every change to detection comes with tests in `tests/core.test.js`, including a round trip (`restore(anonymize(x)) === x`) and a check that the real values do not appear in the output.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `ci:`, `refactor:`, `test:`, `build:`).
- New source files start with `SPDX-License-Identifier: Apache-2.0`.

## Setup

Requirements: Python 3.10 or later, Node.js 22 or later, git. The desktop app itself only runs on Windows, but the core, the browser UI and all tests run on Linux and macOS.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install --require-hashes --no-deps -r requirements-dev.txt
pre-commit install
```

## Checks

`make check` runs the same gates as CI, in order:

```sh
make check      # format, lint, type check, tests, secret scan
make test       # tests only
```

Without make:

```sh
ruff format --check .
ruff check .
mypy --platform win32
pytest --cov
node --test tests/*.test.js
gitleaks git --redact --config .gitleaks.toml .
```

To try the UI, open `src/topomask.html` in a browser.

## Dependencies

Runtime and build dependencies are locked with hashes. To change them, edit the `.in` file and regenerate the lock with [uv](https://github.com/astral-sh/uv):

```sh
uv pip compile requirements.in --python-platform windows --python-version 3.10 --generate-hashes -o requirements.txt
uv pip compile requirements-build.in --python-platform windows --python-version 3.10 --generate-hashes -o requirements-build.txt
uv pip compile requirements-dev.in --python-platform linux --python-version 3.10 --generate-hashes -o requirements-dev.txt
```

Explain in the pull request why a new dependency is needed and check that its license is compatible with Apache-2.0.

## Pull requests

1. Branch from `main` with a typed name (`feat/…`, `fix/…`, `docs/…`).
2. Keep commits focused; describe the why in the body when it is not obvious.
3. Update `CHANGELOG.md` under `Unreleased`.
4. CI must be green.
