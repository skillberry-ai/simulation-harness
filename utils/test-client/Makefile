.PHONY: help setup dev build start stop restart clean test test-watch lint format

PKG := $(shell command -v pnpm >/dev/null 2>&1 && echo pnpm || echo npm)
PIDFILE := .test-client.pid

help:
	@echo "Test Client (PatternFly) — using $(PKG)"
	@echo "  make setup       Install workspace dependencies"
	@echo "  make dev         Run client (Vite :5173) + server (Express :3000) with HMR"
	@echo "  make build       Build SPA + compile server"
	@echo "  make start       Run built server (SPA + proxy on :3000)"
	@echo "  make stop        Stop the started server"
	@echo "  make restart     Restart the started server"
	@echo "  make test        Run all Vitest suites once"
	@echo "  make test-watch  Run Vitest in watch mode"
	@echo "  make lint        ESLint"
	@echo "  make format      Prettier --write"
	@echo "  make clean       Remove node_modules and build output"

setup:
	$(PKG) install

dev:
	$(PKG) run dev --workspace server & \
	$(PKG) run dev --workspace client & \
	wait

build:
	$(PKG) run build

start: build
	@mkdir -p logs
	@node server/dist/index.js > logs/$$(date +%Y%m%d_%H%M%S)_test-client.log 2>&1 & echo $$! > $(PIDFILE)
	@echo "Started (pid $$(cat $(PIDFILE))) on :$${PORT:-3000}"

stop:
	@if [ -f $(PIDFILE) ]; then kill $$(cat $(PIDFILE)) && rm -f $(PIDFILE) && echo "Stopped"; else echo "Not running"; fi

restart: stop start

test:
	$(PKG) run test

test-watch:
	$(PKG) run test:watch

lint:
	$(PKG) run lint

format:
	$(PKG) run format

clean:
	rm -rf node_modules client/node_modules server/node_modules client/dist server/dist $(PIDFILE)
