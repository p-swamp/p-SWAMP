from uuid import uuid4

import pytest


@pytest.fixture
def app():
    """A fresh app name per test, so a broker's leftovers never leak in."""
    return f"t{uuid4().hex[:8]}"
