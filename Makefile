PYTHON := python3
VENV_DIR := .venv
VENV_PYTHON := $(VENV_DIR)/bin/python
VENV_PIP := $(VENV_DIR)/bin/pip
VENV_UVICORN := $(VENV_DIR)/bin/uvicorn
HOST ?= 0.0.0.0
PORT ?= 8000
PID_FILE ?= uvicorn.pid
LOG_FILE ?= uvicorn.log

.PHONY: setup run run-dev stop status logs

setup:
	$(PYTHON) -m venv $(VENV_DIR)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements.txt

run:
	@if [ -f "$(PID_FILE)" ] && kill -0 $$(cat "$(PID_FILE)") 2>/dev/null; then \
		echo "Uvicorn is already running (PID $$(cat "$(PID_FILE)"))"; \
		exit 0; \
	fi
	@nohup $(VENV_UVICORN) main:app --host $(HOST) --port $(PORT) > "$(LOG_FILE)" 2>&1 & echo $$! > "$(PID_FILE)"
	@echo "Started Uvicorn in background (PID $$(cat "$(PID_FILE)"))"
	@echo "Logs: $(LOG_FILE)"

run-dev:
	$(VENV_UVICORN) main:app --host $(HOST) --port $(PORT) --reload

stop:
	@if [ -f "$(PID_FILE)" ] && kill -0 $$(cat "$(PID_FILE)") 2>/dev/null; then \
		kill $$(cat "$(PID_FILE)"); \
		rm -f "$(PID_FILE)"; \
		echo "Stopped Uvicorn"; \
	else \
		echo "Uvicorn is not running"; \
	fi

status:
	@if [ -f "$(PID_FILE)" ] && kill -0 $$(cat "$(PID_FILE)") 2>/dev/null; then \
		echo "Uvicorn is running (PID $$(cat "$(PID_FILE)"))"; \
	else \
		echo "Uvicorn is not running"; \
	fi

logs:
	@tail -f "$(LOG_FILE)"
