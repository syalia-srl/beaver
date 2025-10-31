.PHONY: publish
publish: clean build
	uv publish --token `dotenv -f .env get PYPI_TOKEN`

.PHONY: build
build:
	uv build
	uv pip install -e .[full]

.PHONY: clean
clean:
	rm -rf dist
	rm -rf beaver_db.egg-info
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +

.PHONY: push-docker
push-docker:
	$(eval VERSION := $(shell beaver --version))
	docker build --build-arg VERSION=$(VERSION) -t apiad/beaverdb:$(VERSION) .
	docker tag apiad/beaverdb:$(VERSION) apiad/beaverdb:latest
	docker push apiad/beaverdb:$(VERSION)
	docker push apiad/beaverdb:latest

#
# Your new workflow:
# 1. Before you start work, run `make pull` to get the latest.
# 2. Make your local edits (create/edit/delete files).
# 3. When you're ready, run `make push` to sync your changes.
#

.PHONY: push-issues
push-issues:
	# 1. Run the script to push your local changes to GitHub.
	# This script will also modify any *new* files to add their issue numbers.
	bash push-issues.sh

	# 2. Add *all* changes: your original edits + the script's edits (like new numbers).
	git add issues

	# 3. Commit everything as one single, clean "sync" action.
	git commit -m "Sync local issue changes"


.PHONY: pull-issues
pull-issues:
	# 1. Pulls all issues from GitHub and overwrites local files.
	# This is a "reset" to the remote state.
	bash pull-issues.sh

	# 2. Add all the changes from the pull.
	git add issues

	# 3. Commit the new state.
	git commit -m "Pull remote issues"
