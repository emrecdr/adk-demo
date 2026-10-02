## What changed, and what was learned

## Checks

- [ ] `uv run ruff check . && uv run ruff format --check .` and `uv run pytest -q` pass locally
- [ ] A carried fix sits in the phase that introduced it and in every later phase that carries the file; `git diff --no-index` between neighbouring phases reads as that phase's lesson
- [ ] The phase READMEs' `New:`/`Changed:`/`Unchanged:` sentences are true, and `docs/ITERATION_MAP.md` §3 draws every file
- [ ] Works on both arms, Copilot and Gemini: nothing outside `config.py` names a provider
- [ ] No date and no count of the repository's state added to the docs; nothing reads or prints `.env`
