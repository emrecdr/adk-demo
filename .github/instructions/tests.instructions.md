---
applyTo: "tests/**"
---

# Tests

- `conftest.py` has the plumbing: a `FakeModel` registered for `fake.*`, `load_phase(monkeypatch, phase)`, which
  re-imports a phase with `REVIEW_MODEL=fake` so its real `build_model()`, graph, callbacks and plugins run,
  `demo_repo`, a real repository built by `make_demo_repo.build`, and `fake_provider.raises_when` / `answers_when`,
  which make the provider fail or answer on a text in the system instruction. A test is named as the sentence it
  proves (`test_the_gate_runs_before_any_model`), and an async one carries `@pytest.mark.asyncio`, since
  `asyncio_mode = "strict"`.
- A behaviour is tested in every phase that carries it, from the phase that introduced it on: parametrize over
  `PHASES` from `conftest`, or over the slice of it that has the file, as `test_wiring.py` does.
- A test may run the developer's own git in folders it made (`S607` is ignored for `tests/*`); the reviewer under
  test must still find git by its full path.
- A test asserts one claim a reader can check and prefers the public functions; a helper several tests need goes
  into `conftest.py`, never into a phase.
