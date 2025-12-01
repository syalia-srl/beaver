default: test-unit

.PHONY: docs
docs:
	cd docs && quarto publish gh-pages

.PHONY: format
format:
	black . && git commit -am "Apply code formatting"

.PHONY: format-check
format-check:
	black --check .

.PHONY: type-check
type-check:
	mypy

.PHONY: test-unit test-all

test-unit: format-check
	pytest tests/unit --cov=beaver

test-all: format-check type-check
	pytest --cov=beaver

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
