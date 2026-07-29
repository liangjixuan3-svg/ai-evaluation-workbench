PYTHON ?= python
NPM ?= npm

.PHONY: backend-test frontend-build frontend-test test

backend-test:
	cd backend && $(PYTHON) -m pytest

frontend-build:
	cd frontend && $(NPM) run build

frontend-test:
	cd frontend && $(NPM) run test -- --run

test: backend-test frontend-test
