# The host has no make (see tools.ps1 and QUESTIONS.md); this file keeps the
# contract's `make eval-qa` working on machines that do.
ifeq ($(OS),Windows_NT)
PYTHON ?= .venv/Scripts/python.exe
else
PYTHON ?= .venv/bin/python
endif

.PHONY: eval-qa

eval-qa:
	cd backend && $(PYTHON) -m app.eval_qa
