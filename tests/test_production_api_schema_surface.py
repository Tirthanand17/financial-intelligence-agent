from fastapi.testclient import TestClient

from app.main import api_docs_configuration, app


client = TestClient(app)


def test_api_docs_configuration_fails_closed_in_production() -> None:
    assert api_docs_configuration("production") == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }
    assert api_docs_configuration("  PRODUCTION  ") == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }


def test_api_docs_configuration_keeps_development_documentation() -> None:
    expected = {
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "openapi_url": "/openapi.json",
    }
    assert api_docs_configuration("development") == expected
    assert api_docs_configuration("test") == expected
    assert api_docs_configuration(None) == expected


def test_test_environment_app_keeps_docs_for_developer_workflow() -> None:
    # GitHub CI intentionally runs without APP_ENV=production, so schema tooling
    # remains available to tests/developers while Render production disables it.
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"

    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
