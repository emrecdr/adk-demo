# Phase 1 — hello world

The smallest legal ADK agent, running on both providers the team uses. One
`Agent` with a model, a name, a description and an instruction; no tools, no
state, no callbacks. It greets you, says what it would need to review a
branch, and admits it has no tools yet. Every later phase is this folder plus
one layer.

## What is here

| File | Holds |
|---|---|
| `__init__.py` | `from . import agent`: the one-line package the `adk create` scaffold uses |
| `agent.py` | `root_agent`, the name ADK's loader looks for. Its `name` is the folder name, so what `adk web` lists is what the code says |
| `config.py` | `build_model()`, the only place a provider is named. `REVIEW_PROVIDER=gemini` gives a plain model string, because ADK speaks Gemini natively; `REVIEW_PROVIDER=copilot` gives `LiteLlm("github_copilot/gpt-4.1")`, because everything that is not Gemini goes through LiteLLM. `REVIEW_MODEL` overrides either default. An unknown provider is a `ValueError`, not a silent default |

Both arms are the same `LlmAgent` to the rest of the code. The switch is one
variable in the central `.env` at the repository root, which ADK finds by
walking up from the agent folder; no agent carries a line of code for it
(the commands from phase 4 on load it themselves).

## Run it

```bash
uv run adk run phase_1_hello_world                        # terminal chat
uv run adk web .                                          # browser; pick phase_1_hello_world in the dropdown
uv run python scripts/ask.py phase_1_hello_world "hello"   # one headless turn: the answer and what it cost
```

Expect one sentence of greeting, two sentences on what a reviewer would need
(a repository, a branch, a way to read the change), and a plain statement
that it has no tools yet.

Then set `REVIEW_PROVIDER=gemini` in `.env`, restart, and ask the same
thing. Same agent, same shape of answer; in the web UI only the model
name in the event's Request view changes. That is the lesson of this phase, and the one the
team needs most: the code does not know which provider it is on.

## What to notice

- `Agent` is an alias of `LlmAgent`. `root_agent` is the name the loader looks for.
- The event cards and the side panel show every request the model saw and what
  it cost. They are the debugger for the rest of the talk.
- Copilot, the arm the talk runs on and the one used when none is named, needs no key:
  `uv run python scripts/copilot_login.py` once caches a GitHub device-flow token that LiteLLM reads.
  Gemini needs `GOOGLE_API_KEY` in `.env`.
