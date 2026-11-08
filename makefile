default: test-unit

.PHONY: sync
sync:
	uv sync --extra security --extra remote

# The guide: every Python block runs against the package as it renders.
.PHONY: docs
docs:
	uv run scriptorium render docs/scriptorium.yaml --only site

# The docs gate: the guide renders without a failing block, docs/examples/ matches
# the chapters, the examples run, and rift finds every public class in the docs.
.PHONY: docs-check
docs-check: docs
	! grep -l 'Traceback (most recent call last)' docs/site/*.html
	for c in docs/chapters/*.md; do uv run scriptorium tangle --test $$c -d docs || exit 1; done
	for e in docs/examples/*.py; do [ $$(basename $$e) = __init__.py ] || grep -q "export=$${e#docs/}" docs/chapters/*.md || { echo "$$e is not tangled from the docs"; exit 1; }; done
	tmp=$$(mktemp -d) && for e in docs/examples/*.py; do (cd $$tmp && uv run --project $(CURDIR) python $(CURDIR)/$$e > /dev/null) || exit 1; done
	uvx --from git+https://github.com/apiad/rift@v0.9.0 rift check .

# The Pages artifact, built as .github/workflows/pages.yml builds it.
.PHONY: site
site: docs
	uv run python site/build.py public

.PHONY: check-snippets
check-snippets:
	uv run python site/check_snippets.py

.PHONY: bugfix
bugfix:
	git commit -a -m "Bugfix"

.PHONY: format
format:
	uv run black . && git commit -am "Apply code formatting"

.PHONY: format-check
format-check:
	uv run black --check .

.PHONY: type-check
type-check:
	uv run mypy

.PHONY: test-unit test-concurrency test-all

test-unit: format-check
	uv run pytest tests/unit --cov=beaver

test-concurrency: format-check
	uv run pytest tests/concurrency -m concurrency

test-all: format-check
	uv run pytest --cov=beaver

.PHONY: ci
ci: format-check test-unit

.PHONY: docker-build
docker-build:
	docker build -t beaver-db:latest -f dockerfile .

.PHONY: clean
clean:
	rm -rf dist
	rm -rf beaver_db.egg-info
	rm -rf *.db*
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +

.PHONY: issues
issues:
	gh md-issues push
	sleep 5
	gh md-issues pull
	git add issues && git commit -m "Sync issues"

# Get the current version from pyproject.toml
CURRENT_VERSION := $(shell grep 'version = ' pyproject.toml | cut -d '"' -f 2)

.PHONY: release
release: format-check
	@echo "Current version: ${CURRENT_VERSION}"
	@if [ -z "$(NEW_VERSION)" ]; then \
		echo "ERROR: NEW_VERSION environment variable is not set."; \
		echo "Usage: NEW_VERSION=x.y.z make release"; \
		exit 1; \
	fi
	@make test-all
	@echo "Bumping version from $(CURRENT_VERSION) to $(NEW_VERSION)..."

	@echo Replace version in pyproject.toml
	@sed -i.bak "s/version = \"$(CURRENT_VERSION)\"/version = \"$(NEW_VERSION)\"/" pyproject.toml

	@echo Replace version in beaver/__init__.py
	@sed -i.bak "s/__version__ = \"$(CURRENT_VERSION)\"/__version__ = \"$(NEW_VERSION)\"/" beaver/__init__.py

	@echo Remove backup files
	@rm pyproject.toml.bak beaver/__init__.py.bak

	@uv sync

	@echo "Committing version bump..."
	@git add pyproject.toml beaver/__init__.py uv.lock
	@git commit -m "Bump version to $(NEW_VERSION)"

	@echo "Tagging new version..."
	@git tag "v$(NEW_VERSION)"

	@echo "Pushing commit and tags..."
	@git push
	@git push --tags

	@echo "Creating Github release..."
	@gh release create "v$(NEW_VERSION)" --title "v$(NEW_VERSION)" --notes "Release version $(NEW_VERSION)"

	@echo "✅ Version $(NEW_VERSION) successfully released."

	@uv pip install -e .[full]
