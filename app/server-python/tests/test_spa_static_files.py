"""Tests for SPAStaticFiles: the shell fallback, and the trailing-slash redirect.

The shell references its assets relatively (``./assets/…``), so it only works
when served at a path one segment deep. ``/reference-subapp/`` is two: the
browser would ask for ``/reference-subapp/assets/…``, get the shell back as
text/html, and render a blank page. These tests pin the redirect that prevents
that, and that it stays relative — the server does not know the prefix a reverse
proxy mounts it under.

Hermetic: the mount is pointed at a temp directory and ``get_response`` is
called directly with a hand-built scope, so nothing binds a port and no built
client is needed.
"""

from urllib.parse import urljoin

import pytest
from starlette.exceptions import HTTPException

from server import SPAStaticFiles


@pytest.fixture
def static(tmp_path):
    (tmp_path / "index.html").write_text('<div id="root"></div>')
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("export {}")
    return SPAStaticFiles(directory=tmp_path, html=True)


async def get(static, path, query=b""):
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": query,
        "headers": [],
    }
    return await static.get_response(static.get_path(scope), scope)


async def test_bare_route_serves_the_shell(static):
    response = await get(static, "/reference-subapp")
    assert response.status_code == 200
    assert response.media_type == "text/html"
    assert response.headers["cache-control"] == "no-cache"


async def test_trailing_slash_redirects_to_the_bare_route(static):
    response = await get(static, "/reference-subapp/")
    assert response.status_code == 307
    assert response.headers["location"] == "../reference-subapp"


async def test_redirect_stays_under_a_reverse_proxy_prefix(static):
    # The proxy strips /p-swamp before forwarding, so the server sees the same
    # request as above; only a relative Location puts the prefix back.
    response = await get(static, "/reference-subapp/")
    asked_for = "https://host/p-swamp/reference-subapp/"
    assert (
        urljoin(asked_for, response.headers["location"])
        == "https://host/p-swamp/reference-subapp"
    )


async def test_redirect_keeps_the_query_string(static):
    response = await get(static, "/reference-subapp/", query=b"a=1&b=2")
    assert response.headers["location"] == "../reference-subapp?a=1&b=2"


async def test_each_extra_slash_is_one_more_level_up(static):
    response = await get(static, "/reference-subapp//")
    assert response.headers["location"] == "../../reference-subapp"


async def test_root_is_served_not_redirected(static):
    response = await get(static, "/")
    assert response.status_code == 200
    assert response.media_type == "text/html"


@pytest.mark.parametrize("path", ["/assets/nope.js", "/assets/nope/", "/api/nope/"])
async def test_assets_and_api_keep_their_404(static, path):
    with pytest.raises(HTTPException) as raised:
        await get(static, path)
    assert raised.value.status_code == 404
