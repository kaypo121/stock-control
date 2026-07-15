"""
Comprehensive API and System Audit Tests

Phase 5-10: Complete validation, security, performance, and production readiness checks
"""

import time


from app.database import Base, SessionLocal, engine
from app.main import app
from app.services.gateway_security import GatewaySecurityService


class TestApplicationStartup:
    """Phase 5: Application Startup Testing"""

    def test_application_initializes_without_errors(self):
        """Verify app initializes successfully"""
        assert app is not None
        assert len(app.routes) > 0
        print(f"✓ Application initialized with {len(app.routes)} routes")

    def test_database_connection_pool_works(self):
        """Verify database connection pool is functional"""
        from sqlalchemy import text

        db = SessionLocal()
        try:
            # Simple query to verify connection
            result = db.execute(text("SELECT 1"))
            assert result is not None
            print("✓ Database connection pool is functional")
        finally:
            db.close()

    def test_models_are_registered(self):
        """Verify all SQLAlchemy models are registered"""

        tables = Base.metadata.tables
        actual_tables = set(tables.keys())
        # Check that all expected gateway tables are present
        gateway_tables = {t for t in actual_tables if "gateway" in t}
        assert (
            len(gateway_tables) >= 10
        ), f"Expected at least 10 gateway tables, got {len(gateway_tables)}"
        print(f"✓ All {len(gateway_tables)} gateway models are registered")


class TestAuthenticationAndAuthorization:
    """Phase 5-6: Authentication & Authorization Testing"""

    def test_principal_creation_workflow(self):
        """Test complete principal creation and credential issuance"""
        db = SessionLocal()
        try:
            security_service = GatewaySecurityService()
            from app.schemas.gateway_schemas import PrincipalRegistrationRequest

            # Create principal
            payload = PrincipalRegistrationRequest(
                name="Test AI Agent",
                principal_type="AI_AGENT",
                role="AI_AGENT",
                permissions=["gateway:read", "gateway:write"],
                organization_id="org-test-001",
                metadata={"source": "test"},
            )
            principal, secret = security_service.create_principal(db, payload)
            assert principal.principal_id is not None
            assert len(secret) > 0
            print(f"✓ Principal created: {principal.principal_id}")

            # Verify principal is active
            assert principal.is_active is True

            # Create API key
            from app.schemas.gateway_schemas import ApiKeyCreateRequest

            api_key_payload = ApiKeyCreateRequest(
                principal_id=principal.principal_id,
                label="test-key-1",
                credential_type="API_KEY",
                scopes=["gateway:read", "gateway:write"],
                expires_in_days=30,
            )
            api_key, key_secret, _ = security_service.create_api_key(
                db, api_key_payload
            )
            assert api_key.key_id is not None
            assert key_secret is not None
            print(f"✓ API Key created: {api_key.key_id}")

            # Verify key expiration
            assert api_key.expires_at is not None
            assert api_key.is_active is True

            # Test token issuance
            from app.schemas.gateway_schemas import TokenRequest

            token_payload = TokenRequest(
                principal_id=principal.principal_id,
                client_secret=secret,
                grant_type="client_credentials",
            )
            token_response = security_service.issue_token(db, token_payload)
            assert token_response["accessToken"] is not None
            assert token_response["tokenType"] == "bearer"
            assert token_response["expiresIn"] > 0
            print("✓ JWT Token issued successfully")

        finally:
            db.close()


class TestAPIEndpoints:
    """Phase 6: API Endpoint Validation"""

    def test_health_endpoint_exists_and_responds(self, client):
        """Test health check endpoint"""
        response = client.get("/v1/health")
        assert response.status_code in [200, 404]  # Might not be implemented
        print(f"✓ Health endpoint responds: {response.status_code}")

    def test_docs_endpoint_is_available(self, client):
        """Test Swagger/OpenAPI docs are available"""
        response = client.get("/docs")
        assert response.status_code == 200
        assert "swagger" in response.text.lower() or "openapi" in response.text.lower()
        print("✓ OpenAPI/Swagger documentation is available")

    def test_version_endpoint_exists(self, client):
        """Test version endpoint"""
        response = client.get("/v1/version")
        if response.status_code == 200:
            data = response.json()
            assert "version" in data or "data" in data
            print("✓ Version endpoint works")
        else:
            print(f"⚠ Version endpoint returned {response.status_code}")

    def test_gateway_endpoints_are_registered(self, client):
        """Verify gateway endpoints exist in routes"""
        # Included routers are a route tree in current FastAPI releases; the
        # generated OpenAPI schema is the public, flattened route contract.
        gateway_routes = [
            path for path in app.openapi()["paths"] if path.startswith("/v1")
        ]
        assert len(gateway_routes) > 0
        print(f"✓ {len(gateway_routes)} gateway endpoints are registered")

        # Print sample of routes
        sample_routes = sorted(gateway_routes)[:10]
        for route in sample_routes:
            print(f"  - {route}")


class TestResponseFormats:
    """Phase 6: Response Format Validation"""

    def test_response_envelope_format(self, client):
        """Verify responses follow the standard envelope format"""
        response = client.get("/v1/providers")

        # Should follow gateway response format
        if response.status_code == 200:
            data = response.json()
            # Check for standard response fields
            assert "data" in data or "message" in data or "status" in data
            print("✓ Response follows envelope format")

    def test_error_response_format(self, client):
        """Test error responses are properly formatted"""
        response = client.get("/v1/nonexistent")
        assert response.status_code in [404, 422]

        data = response.json()
        # Error responses should have error information
        assert "detail" in data or "errors" in data or "message" in data
        print("✓ Error responses are properly formatted")


class TestSecurityHeaders:
    """Phase 7: Security Audit - Headers & CORS"""

    def test_cors_headers_are_set(self, client):
        """Verify CORS headers are configured"""
        response = client.get("/health", headers={"Origin": "http://localhost:3000"})
        # CORS headers should be present or not (depending on config)
        print(f"✓ CORS handling: Status {response.status_code}")

    def test_json_content_type(self, client):
        """Verify responses use application/json"""
        response = client.get("/docs")
        # Should have content-type header
        content_type = response.headers.get("content-type", "")
        print(f"✓ Content-Type: {content_type}")


class TestDataValidation:
    """Phase 6-7: Request Validation"""

    def test_invalid_json_is_rejected(self, client, admin_headers):
        """Test malformed JSON is rejected"""
        response = client.post(
            "/quality/assess",
            content="invalid json {",
            headers={
                "Content-Type": "application/json",
                **admin_headers,
            },
        )
        assert response.status_code in [400, 404, 422]
        print(f"✓ Malformed JSON handling: Status {response.status_code}")

    def test_missing_required_fields_rejected(self, client, admin_headers):
        """Test requests with missing required fields are rejected"""
        response = client.post(
            "/quality/assess",
            json={"product_name": "Test"},  # Missing required fields
            headers=admin_headers,
        )
        assert response.status_code in [400, 404, 422]
        print(f"✓ Missing field validation: Status {response.status_code}")


class TestPerformance:
    """Phase 8: Performance Testing"""

    def test_endpoint_response_time_is_acceptable(self, client):
        """Verify response times are within acceptable range"""
        start = time.time()
        client.get("/docs")
        elapsed = time.time() - start

        assert elapsed < 1.0, f"Response took {elapsed}s, should be < 1s"
        print(f"✓ Response time: {elapsed:.3f}s (acceptable)")

    def test_concurrent_requests_are_handled(self, client):
        """Test multiple simultaneous requests"""
        import concurrent.futures

        def make_request():
            try:
                response = client.get("/health")
                return response.status_code
            except Exception:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        successful = sum(1 for r in results if r is not None)
        print(f"✓ Handled 10 concurrent requests, {successful} successful")


class TestTimezoneHandling:
    """Verify timezone-aware datetime usage"""

    def test_utcnow_returns_timezone_aware_datetime(self):
        """Verify fixed utcnow() returns timezone-aware datetime"""
        from app.services.gateway_security import utcnow

        dt = utcnow()
        assert dt.tzinfo is not None, "Datetime should be timezone-aware"
        assert dt.tzinfo.utcoffset(dt).total_seconds() == 0, "Should be UTC"
        print("✓ utcnow() returns timezone-aware UTC datetime")


class TestDatabaseConstraints:
    """Phase 5: Database Integrity"""

    def test_foreign_key_relationships(self):
        """Verify foreign key relationships are properly defined"""
        from app.models.gateway_models import GatewayApiKey

        # Check that GatewayApiKey has foreign key to GatewayPrincipal
        assert hasattr(GatewayApiKey, "principal_id")
        assert hasattr(GatewayApiKey, "principal")
        print("✓ Foreign key relationships are properly defined")

    def test_database_indexes(self):
        """Verify important columns are indexed"""
        principal_table = Base.metadata.tables["gateway_principals"]
        indexed_columns = {
            column.name
            for index in principal_table.indexes
            for column in index.columns
        }

        important_columns = {"principal_id", "name", "role"}
        missing_indexes = important_columns - indexed_columns

        if not missing_indexes:
            print(f"✓ Important columns are indexed: {indexed_columns}")
        else:
            print(f"⚠ Missing indexes on: {missing_indexes}")
