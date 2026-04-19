"""Support ``python -m agentspec`` as an alternative to the installed
``agentspec`` console script.

Useful for:

- Development without `pip install -e .` (works with `PYTHONPATH=src`).
- Demos / smoke scripts that want an unambiguous entry point without
  depending on the virtualenv's shebang resolution.
- Bundled distributions (zipapps, Nix-packaged wheels) where the
  console-script wrapper may not exist.
"""

from __future__ import annotations

from agentspec.cli.main import main

if __name__ == "__main__":
    main()
