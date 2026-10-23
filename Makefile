# Tests and the visual bench run in Docker: WeasyPrint needs Pango and weasyvsdx needs vsd2xhtml, which macOS lacks.
IMAGE ?= weasyvsdx-test
BASE ?= python:3.14-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170
# The Azure diagrams and their references stay outside the repository, see tools/corpus/azure.py
CACHE ?= $(HOME)/.cache/weasyvsdx
RUN = docker run --rm --volume "$(CURDIR):/src"
VISUAL = $(RUN) --volume "$(CACHE):/cache" --env WEASYVSDX_CACHE=/cache $(IMAGE):visual uv run --frozen --all-extras

.PHONY: lint test test-image azure visual visual-image visual-baseline visual-check references comparison

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src tests tools

test-image:
	docker build --file Dockerfile.test --target test --build-arg BASE="$(BASE)" --tag $(IMAGE):test .

test: test-image
	$(RUN) $(IMAGE):test

# Download the Azure diagrams of corpus/azure.json into the cache, once
azure:
	mkdir -p "$(CACHE)"
	WEASYVSDX_CACHE="$(CACHE)" python3 tools/corpus/azure.py fetch $(ARGS)

visual-image:
	docker build --file Dockerfile.test --target visual --build-arg BASE="$(BASE)" --tag $(IMAGE):visual .

# make visual ARGS="--only azure" renders one group or name
visual: visual-image azure
	$(VISUAL) python tools/visual/bench.py $(ARGS)

# Store the mismatch of each drawing in corpus/baseline.json
visual-baseline: visual-image azure
	$(VISUAL) python tools/visual/bench.py --write-baseline corpus/baseline.json

# Compare with corpus/baseline.json: fails when a drawing got worse
visual-check: visual-image azure
	$(VISUAL) python tools/visual/bench.py --against corpus/baseline.json

# Export the first page of each drawing with the LibreOffice Draw of the visual image: the corpus files into
# corpus/reference/libreoffice, the Azure diagrams into the cache
references: visual-image azure
	$(VISUAL) python tools/visual/make_references.py $(ARGS)

# Render the drawings of the repository as weasyvsdx and as the plain SVG of vsd2xhtml, then write the panels
# into corpus/render, corpus/COMPARISON.md and corpus/comparison.html (GitHub Pages)
comparison: visual-image
	$(VISUAL) python tools/visual/bench.py --corpus-only --out tools/visual/out/weasyvsdx
	$(VISUAL) python tools/visual/bench.py --corpus-only --plain --out tools/visual/out/libvisio
	$(VISUAL) python tools/visual/comparison.py
