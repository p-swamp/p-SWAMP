"""A minimal example test — the shape to copy for a new server unit test.

It shows the two things every suite here needs and nothing else: how to import a
server package under ``src/`` by name (``pythonpath = ["src"]`` in
``pyproject.toml`` puts it on the path, same as the running server), and a plain
``assert``. Run the whole suite with ``uv run pswamp test server``, or
just this file with ``uv run pswamp test server tests/test_example.py``.

The function under test, ``wire.sample``, is a good first example because it is
pure and hermetic — no event loop, no Hub, no socket — and it enforces the wire
format's "NaN is null" rule (see the module docstring in ``pswamp_web/wire.py``).
"""

import math

from pswamp_web.wire import sample


def test_finite_value_passes_through():
    assert sample(1.5) == 1.5


def test_none_stays_none():
    assert sample(None) is None


def test_nan_and_infinities_become_null():
    # The whole point of sample(): JSON.parse rejects a bare NaN token, and NaN is
    # the normal case here (a TimeWindow is all-NaN until it fills).
    assert sample(math.nan) is None
    assert sample(math.inf) is None
    assert sample(-math.inf) is None


def test_ndigits_rounds():
    assert sample(3.14159, ndigits=2) == 3.14
