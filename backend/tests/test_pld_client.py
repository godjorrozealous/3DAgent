import httpx
import pytest
import pld_client


class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append((request.method, request.url.path))
        key = (request.method, request.url.path)
        body = self.routes.get(key, {"ok": True})
        return httpx.Response(200, json=body)


@pytest.fixture
def mock_transport(monkeypatch):
    routes = {
        ("GET", "/api/skills"): {"skills": [{"name": "s1"}]},
        ("GET", "/api/skills/default"): {"default_skill": "s1", "available_skills": ["s1"]},
        ("POST", "/api/skills/default"): {"success": True, "default_skill": "s1"},
        ("POST", "/api/skills/reset"): {"success": True},
        ("GET", "/api/templates"): {"templates": [{"name": "t.docx", "is_active": False}]},
        ("POST", "/api/templates/upload"): {"success": True, "template": {"name": "t.docx"}},
        ("POST", "/api/templates/activate"): {"success": True, "active_template": "t.docx"},
        ("DELETE", "/api/templates/t.docx"): {"success": True},
    }
    transport = MockTransport(routes)
    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw["transport"] = transport
        return real(*a, **kw)

    monkeypatch.setattr(pld_client.httpx, "AsyncClient", factory)
    return transport


async def test_skills_and_templates(mock_transport):
    assert (await pld_client.list_skills())["skills"][0]["name"] == "s1"
    assert (await pld_client.get_default_skill())["default_skill"] == "s1"
    assert (await pld_client.set_default_skill("s1"))["success"] is True
    assert (await pld_client.reset_skills())["success"] is True
    assert (await pld_client.list_templates())["templates"][0]["name"] == "t.docx"
    assert (await pld_client.upload_template(b"data", "t.docx"))["success"] is True
    assert (await pld_client.activate_template("t.docx"))["active_template"] == "t.docx"
    assert (await pld_client.delete_template("t.docx"))["success"] is True
    methods = [m for m, _ in mock_transport.requests]
    assert "DELETE" in methods and "POST" in methods
