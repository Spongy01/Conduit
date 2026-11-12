"""GET /admin/ui: the static admin page. Inert markup, so no key is needed to
load it; every data call it makes is admin-key protected."""
import re


async def test_admin_ui_serves_html_without_a_key(client):
    r = await client.get("/admin/ui")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Conduit Admin" in r.text


async def test_admin_ui_sets_restrictive_csp_with_matching_nonce(client):
    r = await client.get("/admin/ui")

    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "'unsafe-inline'" not in csp
    assert "http://" not in csp and "https://" not in csp
    nonce = re.search(r"script-src 'nonce-([^']+)'", csp).group(1)
    assert f'nonce="{nonce}"' in r.text  # the page's inline script carries this request's nonce


async def test_admin_ui_nonce_differs_per_request(client):
    first = (await client.get("/admin/ui")).headers["content-security-policy"]
    second = (await client.get("/admin/ui")).headers["content-security-policy"]
    assert first != second


async def test_admin_ui_has_no_external_resources(client):
    body = (await client.get("/admin/ui")).text

    assert not re.search(r"""(?:src|href|action)\s*=\s*["']?\s*(?:https?:)?//""", body)
    assert "@import" not in body
    assert not re.search(r"url\(", body)


async def test_admin_ui_never_uses_browser_storage(client):
    body = (await client.get("/admin/ui")).text

    for forbidden in ("localStorage", "sessionStorage", "document.cookie", "indexedDB"):
        assert forbidden not in body
