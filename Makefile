# SPDX-License-Identifier: Apache-2.0
.PHONY: check format lint typecheck test secrets

check: format lint typecheck test secrets

format:
	ruff format --check .

lint:
	ruff check .

typecheck:
	mypy --platform win32

test:
	pytest --cov
	node --test tests/*.test.js

secrets:
	gitleaks git --redact --config .gitleaks.toml .
