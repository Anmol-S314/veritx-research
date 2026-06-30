.PHONY: setup run test docker clean dist

setup:        ## Create venv (CPU-only), install deps, bootstrap .env + default project
	bash setup.sh

run:          ## Start the server on http://localhost:8001
	./run.sh

test:         ## Run the end-to-end test suite
	.venv/bin/python -m pytest tests/ -q

audio:        ## List audio devices + live capture level meter
	.venv/bin/python -m mis.audio_check --test

docker:       ## Build + run the container (CPU image)
	docker build -t meeting-intel . && docker run -p 8001:8001 meeting-intel

clean:        ## Remove caches (keeps venv, projects, .env)
	find . -name __pycache__ -type d -prune -exec rm -rf {} + ; rm -rf .pytest_cache

dist:         ## Build the shippable zip (source only — never bundles .env, venv, or project data)
	@rm -rf dist-tmp && mkdir -p dist-tmp/meeting-intelligence
	@cp -r mis tests .github \
		setup.sh run.sh requirements.txt requirements-dev.txt \
		qwen_meeting.html SPEC.md README.md Makefile Dockerfile DESIGN_DOC.md \
		.gitignore .env.example  dist-tmp/meeting-intelligence/
	@find dist-tmp -name __pycache__ -type d -prune -exec rm -rf {} + ; find dist-tmp -name '*.pyc' -delete
	@rm -rf dist-tmp/meeting-intelligence/mis/rag_state   # strip stray legacy index, never ship data
	@test ! -e dist-tmp/meeting-intelligence/.env  # safety: secrets must never ship
	@cd dist-tmp && zip -rq ../meeting-intelligence.zip meeting-intelligence
	@rm -rf dist-tmp
	@echo "Built meeting-intelligence.zip:"; unzip -l meeting-intelligence.zip | tail -2
