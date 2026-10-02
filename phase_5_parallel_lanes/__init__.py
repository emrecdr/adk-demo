"""Nothing is imported here, unlike the scaffold's `from . import agent`. The folder is also a command, and
`python -m <phase>.review` imports this package before the command's `main` has read the root `.env`; `agent.py`
builds its agents when it is imported, so the scaffold's line would build them on the shell's provider rather than
the one `.env` names. ADK's loader finds `agent.py` by itself."""
