.PHONY: help sync web run ask diff demo-repo demo-fix review rehearse copilot-login test lint format ci

REPO ?=  # blank: the scripts and the commands default to the demo repository in the temp directory
BASE ?= main
HEAD ?= feature/payments
PHASE ?= phase_1_hello_world
FROM ?= phase_5_parallel_lanes
TO ?= phase_6_reviewer
CLI ?= phase_6_reviewer

help:
	@echo "make sync                          - install (uv)"
	@echo "make web                           - adk web .  (every phase in one dropdown)"
	@echo "make run PHASE=phase_2_preflight   - adk run, terminal chat with one phase"
	@echo "make ask PHASE=... MSG='...'       - one headless turn through the Runner, no UI"
	@echo "make diff FROM=phase_3_changed_files TO=phase_4_first_review - the lesson, as a diff"
	@echo "make demo-repo                     - build the throwaway repository the demo reviews"
	@echo "make review [CLI=phase_4_first_review] [ARGS='--profile gates-only'] - a phase's command over the demo repository; phase 6 by default"
	@echo "make review CLI=phase_7_hardened BASE= ARGS=--all - phase 7 over every file at the head"
	@echo "make demo-fix                      - commit the two fixes on the demo branch, then make review again: exit 0"
	@echo "make rehearse                      - print every phase's demo line, in order (no model call)"
	@echo "make copilot-login                 - one-time GitHub device-flow login for the copilot arm"
	@echo "make test / lint / format / ci"

sync:
	uv sync --locked

web:
	uv run adk web .

run:
	uv run adk run $(PHASE)

ask:
	uv run python scripts/ask.py $(PHASE) "$(MSG)"

diff:
	@git diff --no-index -- $(FROM) $(TO) || true

demo-repo:
	uv run python scripts/make_demo_repo.py $(REPO)

demo-fix:
	uv run python scripts/make_demo_repo.py $(REPO) --fix

review:
	uv run python -m $(CLI).review $(REPO) $(if $(BASE),--base $(BASE)) --head $(HEAD) $(ARGS)

rehearse:
	uv run python scripts/rehearse.py --dry-run

copilot-login:
	uv run python scripts/copilot_login.py $(ARGS)

test:
	uv run pytest -q

lint:
	uv run ruff check . && uv run ruff format --check .

format:
	uv run ruff check --fix . && uv run ruff format .

ci: lint test
