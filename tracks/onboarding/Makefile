# Onboarding Track — Makefile
.PHONY: setup lint test sim clean

setup:
	@echo "Setting up onboarding environment..."

lint:
	@echo "No lint for onboarding."

test:
	@echo "Running onboarding sanity checks..."
	@python3 -c "import numpy; print('NumPy OK:', numpy.__version__)"
	@python3 -c "import matplotlib; print('Matplotlib OK:', matplotlib.__version__)"

sim:
	@echo "No simulation for onboarding."

clean:
	@rm -rf results/ __pycache__/
