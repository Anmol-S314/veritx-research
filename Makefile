# VeritX Research — Top-Level Makefile
.PHONY: all setup lint test sim report clean docker-build docker-push docker-run

TRACK ?= onboarding

# Default
all: setup lint test

setup:
	@echo "Setting up track: $(TRACK)"
	@make -C tracks/$(TRACK) setup

lint:
	@echo "Linting track: $(TRACK)"
	@make -C tracks/$(TRACK) lint

test:
	@echo "Testing track: $(TRACK)"
	@make -C tracks/$(TRACK) test

sim:
	@echo "Running simulation for track: $(TRACK)"
	@make -C tracks/$(TRACK) sim

report:
	@echo "Generating report..."
	@mkdir -p report
	@./scripts/generate_report.py

clean:
	@echo "Cleaning..."
	@for d in tracks/*/; do make -C $$d clean 2>/dev/null || true; done
	@rm -rf report/ results/

docker-build:
	docker build -t veritx/tools-base:latest .

docker-push:
	$(eval REGISTRY ?= ghcr.io/anmol-s314)
	docker tag veritx/tools-base:latest $(REGISTRY)/veritx-tools-base:latest
	docker push $(REGISTRY)/veritx-tools-base:latest

docker-run:
	docker run --rm -it -v $(PWD):/workspace veritx/tools-base:latest
