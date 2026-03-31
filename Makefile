PYTHON := python3
VENV_DIR := .venv
VENV_PYTHON := $(VENV_DIR)/bin/python
VENV_PIP := $(VENV_DIR)/bin/pip
VENV_UVICORN := $(VENV_DIR)/bin/uvicorn
HOST ?= 0.0.0.0
PORT ?= 8000

.PHONY: setup run run-dev

setup:
	$(PYTHON) -m venv $(VENV_DIR)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements.txt

run:
	$(VENV_UVICORN) main:app --host $(HOST) --port $(PORT)

run-dev:
	$(VENV_UVICORN) main:app --host $(HOST) --port $(PORT) --reload
