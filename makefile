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