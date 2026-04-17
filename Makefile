.PHONY: install run test

SYSTEM_DEPS_zypper  = ffmpeg pipewire pipewire-pulseaudio pulseaudio-utils
SYSTEM_DEPS_apt     = ffmpeg pipewire pipewire-pulse pulseaudio-utils
SYSTEM_DEPS_dnf     = ffmpeg pipewire pipewire-pulseaudio pulseaudio-utils

install:
	@# --- system packages ---
	@missing=""; \
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
	fi
	@# --- python packages ---
	@missing=""; \
	for pkg in fastapi uvicorn httpx pytest; do \
		python3 -c "import $$pkg" 2>/dev/null || missing="$$missing $$pkg"; \
	done; \
	if [ -n "$$missing" ]; then \
		echo "Missing Python packages:$$missing"; \
		echo "Install with: pip install -r requirements.txt"; \
		exit 1; \
	else \
		echo "Python dependencies already installed."; \
	fi

run:
	python3 -c "from config import config; import uvicorn; uvicorn.run('app:app', host=config['host'], port=config['port'])"

test:
	python3 -m pytest tests/ -v
