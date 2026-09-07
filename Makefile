.PHONY: install run test

VENV     := venv
PYTHON   := $(VENV)/bin/python3
PIP      := $(VENV)/bin/pip

SYSTEM_DEPS_zypper  = ffmpeg pipewire pipewire-pulseaudio pulseaudio-utils
SYSTEM_DEPS_apt     = ffmpeg pipewire pipewire-pulse pulseaudio-utils
SYSTEM_DEPS_dnf     = ffmpeg pipewire pipewire-pulseaudio pulseaudio-utils
SYSTEM_DEPS_brew    = ffmpeg blackhole-2ch blackhole-16ch

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt

install: $(VENV)/bin/activate
	@# --- system packages ---
	@UNAME=$$(uname); \
	if [ "$$UNAME" = "Darwin" ]; then \
		missing=""; \
		for cmd in ffmpeg ffprobe; do \
			command -v $$cmd >/dev/null 2>&1 || missing="$$missing $$cmd"; \
		done; \
		if [ -n "$$missing" ]; then \
			echo "Installing system dependencies via Homebrew..."; \
			brew install $(SYSTEM_DEPS_brew); \
		else \
			echo "System dependencies already installed."; \
		fi; \
	else \
		missing=""; \
		for cmd in ffmpeg ffprobe pw-loopback pactl paplay; do \
			command -v $$cmd >/dev/null 2>&1 || missing="$$missing $$cmd"; \
		done; \
		if [ -n "$$missing" ]; then \
			echo "Missing system tools:$$missing — installing..."; \
			if command -v zypper >/dev/null 2>&1; then \
				sudo zypper install -y $(SYSTEM_DEPS_zypper); \
			elif command -v apt-get >/dev/null 2>&1; then \
				sudo apt-get install -y $(SYSTEM_DEPS_apt); \
			elif command -v dnf >/dev/null 2>&1; then \
				sudo dnf install -y $(SYSTEM_DEPS_dnf); \
			else \
				echo "Could not detect package manager. Please install manually:$$missing"; \
				exit 1; \
			fi; \
		else \
			echo "System dependencies already installed."; \
		fi; \
	fi

run: $(VENV)/bin/activate
	$(PYTHON) -c "from config import config; import uvicorn; uvicorn.run('app:app', host=config['host'], port=config['port'])"

test: $(VENV)/bin/activate
	$(PYTHON) -m pytest tests/ -v
