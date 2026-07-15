import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Use a shared in-memory SQLite database for the full test run.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["GATEWAY_BOOTSTRAP_TOKEN"] = "test-bootstrap-token"

from app.database import Base, get_db  # noqa: E402
import app.database as app_database  # noqa: E402

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

app_database.engine = engine
app_database.SessionLocal = TestingSessionLocal

import app.main as app_main  # noqa: E402
import app.services.gateway_service as gateway_service  # noqa: E402
from app.main import app  # noqa: E402
from app.services.gateway_service import gateway_orchestrator  # noqa: E402

# Create all tables after importing models through app.main.
Base.metadata.create_all(bind=engine)


@pytest.fixture(scope="function")
def db_session():
    # Create tables
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        # Drop tables
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    # Override get_db dependency
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app_database.engine = engine
    app_database.SessionLocal = TestingSessionLocal
    app_main.database.engine = engine
    app_main.database.SessionLocal = TestingSessionLocal
    gateway_service.SessionLocal = TestingSessionLocal
    gateway_orchestrator.bootstrap(db_session)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def test_lifespan(_app):
        """Keep tests isolated from the application's configured database."""
        yield

    app.router.lifespan_context = test_lifespan
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.router.lifespan_context = original_lifespan
        app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def admin_headers(client):
    principal_response = client.post(
        "/v1/auth/principals",
        json={
            "name": "Gateway Admin",
            "principal_type": "ADMIN",
            "role": "ADMIN",
            "organizationId": "org-1",
            "workspaceId": "workspace-1",
            "projectId": "project-1",
        },
        headers={"X-Gateway-Bootstrap-Token": "test-bootstrap-token"},
    )
    assert principal_response.status_code == 201
    principal_payload = principal_response.json()["data"]
    token_response = client.post(
        "/v1/auth/token",
        json={
            "principalId": principal_payload["principal"]["principalId"],
            "clientSecret": principal_payload["clientSecret"],
            "grantType": "client_credentials",
        },
    )
    assert token_response.status_code == 200
    return {
        "Authorization": f"Bearer {token_response.json()['data']['accessToken']}"
    }
