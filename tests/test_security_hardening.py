from io import BytesIO

from app.api.integration_endpoints import _build_upload_path


def _issue_token_for_principal(client, principal_id, client_secret):
    response = client.post(
        "/v1/auth/token",
        json={
            "principalId": principal_id,
            "clientSecret": client_secret,
            "grantType": "client_credentials",
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['accessToken']}"}


def test_first_principal_requires_bootstrap_token(client):
    response = client.post(
        "/v1/auth/principals",
        json={
            "name": "Gateway Admin",
            "principal_type": "ADMIN",
            "role": "ADMIN",
        },
    )

    assert response.status_code == 401
    assert response.json()["errors"][0]["code"] == "INVALID_BOOTSTRAP_TOKEN"


def test_stock_routes_require_authentication(client):
    response = client.get("/stock/current")

    assert response.status_code == 401
    assert response.json()["errors"][0]["code"] == "AUTH_REQUIRED"


def test_integration_upload_path_is_sanitized(monkeypatch, tmp_path):
    monkeypatch.setattr("app.api.integration_endpoints.DATA_RAW_DIR", tmp_path)

    save_path = _build_upload_path("../nested/escape.csv")

    assert save_path.parent == tmp_path
    assert save_path.name.endswith("_escape.csv")
    assert ".." not in save_path.name


def test_file_download_is_limited_to_owner(client, admin_headers):
    second_principal_response = client.post(
        "/v1/auth/principals",
        json={
            "name": "Read Only User",
            "principal_type": "READ_ONLY",
            "role": "READ_ONLY",
            "organizationId": "org-2",
        },
        headers=admin_headers,
    )
    assert second_principal_response.status_code == 201
    second_payload = second_principal_response.json()["data"]
    second_headers = _issue_token_for_principal(
        client,
        second_payload["principal"]["principalId"],
        second_payload["clientSecret"],
    )

    upload_response = client.post(
        "/v1/files/upload",
        headers=admin_headers,
        files={
            "file": (
                "report.csv",
                BytesIO(b"farmer,product\nAma,Maize\n"),
                "text/csv",
            )
        },
    )
    assert upload_response.status_code == 201
    file_id = upload_response.json()["data"]["fileId"]

    denied_response = client.get(f"/v1/files/{file_id}", headers=second_headers)

    assert denied_response.status_code == 403
    assert denied_response.json()["errors"][0]["code"] == "FILE_ACCESS_DENIED"
