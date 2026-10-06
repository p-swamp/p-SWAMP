# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the p-SWAMP Project.

"""Write the api contract to a file. Driven by uv run pswamp api generate.

    python tools/dump_openapi.py <output.json>

Imports the FastAPI app and asks it for its own document, so the committed
contract is by construction the same one the running server serves at
/openapi.json -- there is no second description of the api to keep in step.

Importing `server` needs src/ on the path but NOT the working directory to be
src/, which is why that is arranged here rather than in the shell script. The
import is cheap: it binds no port, starts no threads, and does not touch the
recorded PMU dataset -- `replay.load_recording` is `lru_cache`d and lazy, so the
first pipeline pays for it, not this. Measured ~0.2 s to import and ~0.02 s to
build the document. The Dockerfile already does `python -c "import server"` as a
build smoke test, so this is a well-trodden path.

Output is pretty-printed with sorted keys. Both matter: this file is committed and
read in review, so the diff for a changed endpoint should be the endpoint, not a
reshuffle of unrelated keys.
"""

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import server  # noqa: E402  (must follow the sys.path line above)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <output.json>", file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    document = server.app.openapi()
    # Trailing newline so the file is a well-formed text file and diffs cleanly.
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
