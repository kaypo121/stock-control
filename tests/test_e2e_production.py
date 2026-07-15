"""
End-to-end CRUD verification against the deployed Agriculture Stock Control API.

Run:
    python -m pytest tests/test_e2e_production.py -v -s

Environment variables (optional overrides):
    E2E_BASE_URL          - default https://agriculture-db.onrender.com
    E2E_PRINCIPAL_ID      - gateway principal UUID
    E2E_CLIENT_SECRET     - gateway client secret
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
import pytest

BASE_URL = os.environ.get("E2E_BASE_URL", "https://agriculture-db.onrender.com").rstrip("/")
PRINCIPAL_ID = os.environ.get(
    "E2E_PRINCIPAL_ID", "e494e7d7-842d-4e2b-8a55-f802e159c45e"
)
CLIENT_SECRET = os.environ.get(
    "E2E_CLIENT_SECRET", "agw_client_EOSdOxL8DqZRU4LXlJPuvTq9-v9Q9tk6KIl0dJJd5F8"
)

MAX_RETRIES = 5
BACKOFF_SECONDS = [2, 4, 8, 16, 30]


@dataclass
class E2EResult:
    operation: str
    method: str
    path: str
    status_code: Optional[int] = None
    passed: bool = False
    detail: str = ""
    response_snippet: str = ""


@dataclass
class E2EContext:
    client: httpx.Client
    token: str = ""
    farmer_id: Optional[int] = None
    product_id: Optional[int] = None
    transaction_id: Optional[int] = None
    results: List[E2EResult] = field(default_factory=list)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


def _request_with_retry(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    json: Optional[Dict[str, Any]] = None,
) -> httpx.Response:
    """Retry on cold-start / transient failures (502, 503, 504, connection errors)."""
    url = f"{BASE_URL}{path}"
    last_exc: Optional[Exception] = None
    for attempt, wait in enumerate(BACKOFF_SECONDS[:MAX_RETRIES]):
        try:
            response = client.request(method, url, headers=headers, json=json, timeout=60.0)
            if response.status_code in (502, 503, 504) and attempt < MAX_RETRIES - 1:
                time.sleep(wait)
                continue
            return response
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("Request failed after retries")


def _record(
    ctx: E2EContext,
    operation: str,
    method: str,
    path: str,
    response: httpx.Response,
    *,
    expect_status: int | tuple[int, ...] = 200,
    check: Optional[callable] = None,
) -> None:
    expected = (expect_status,) if isinstance(expect_status, int) else expect_status
    body_text = response.text[:300]
    passed = response.status_code in expected
    detail = ""
    if passed and check:
        try:
            passed = bool(check(response))
            if not passed:
                detail = "Response body check failed"
        except Exception as exc:  # noqa: BLE001
            passed = False
            detail = f"Check raised: {exc}"
    elif not passed:
        detail = f"Expected {expected}, got {response.status_code}"

    ctx.results.append(
        E2EResult(
            operation=operation,
            method=method,
            path=path,
            status_code=response.status_code,
            passed=passed,
            detail=detail,
            response_snippet=body_text,
        )
    )
    assert passed, f"{operation} failed: {detail}\n{body_text}"


def _auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def e2e_ctx() -> E2EContext:
    with httpx.Client(follow_redirects=True) as client:
        ctx = E2EContext(client=client)
        yield ctx
        _print_summary(ctx)


def _print_summary(ctx: E2EContext) -> None:
    print("\n" + "=" * 72)
    print(f"E2E Production Test Summary (run_id={ctx.run_id}, base={BASE_URL})")
    print("=" * 72)
    for r in ctx.results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.operation:30s} {r.method:6s} {r.path:35s} -> {r.status_code}")
        if not r.passed and r.detail:
            print(f"         {r.detail}")
    passed = sum(1 for r in ctx.results if r.passed)
    total = len(ctx.results)
    print("-" * 72)
    print(f"  Total: {passed}/{total} passed")
    print("=" * 72 + "\n")


class TestProductionE2E:
    """Full send/receive/update/retrieve flow against live Render deployment."""

    def test_01_health_warmup(self, e2e_ctx: E2EContext) -> None:
        resp = _request_with_retry(e2e_ctx.client, "GET", "/health")
        _record(e2e_ctx, "Health warmup", "GET", "/health", resp, expect_status=200)

    def test_02_auth_token(self, e2e_ctx: E2EContext) -> None:
        resp = _request_with_retry(
            e2e_ctx.client,
            "POST",
            "/v1/auth/token",
            json={
                "principalId": PRINCIPAL_ID,
                "clientSecret": CLIENT_SECRET,
                "grantType": "client_credentials",
            },
        )

        def _has_token(r: httpx.Response) -> bool:
            data = r.json()
            return bool(data.get("data", {}).get("accessToken"))

        _record(
            e2e_ctx,
            "Auth token issuance",
            "POST",
            "/v1/auth/token",
            resp,
            expect_status=200,
            check=_has_token,
        )
        e2e_ctx.token = resp.json()["data"]["accessToken"]

    def test_03_create_farmer(self, e2e_ctx: E2EContext) -> None:
        assert e2e_ctx.token, "Auth token required"
        payload = {
            "full_name": f"E2E Farmer {e2e_ctx.run_id}",
            "phone_number": "+233200000001",
            "region": "Ashanti",
            "district": "Ejura",
            "farm_name": f"E2E Farm {e2e_ctx.run_id}",
        }
        resp = _request_with_retry(
            e2e_ctx.client,
            "POST",
            "/stock/farmers",
            headers=_auth_headers(e2e_ctx.token),
            json=payload,
        )

        def _farmer_created(r: httpx.Response) -> bool:
            body = r.json()
            e2e_ctx.farmer_id = body.get("farmer_id")
            return e2e_ctx.farmer_id is not None and body.get("full_name") == payload["full_name"]

        _record(
            e2e_ctx,
            "CREATE farmer",
            "POST",
            "/stock/farmers",
            resp,
            expect_status=201,
            check=_farmer_created,
        )

    def test_04_create_product(self, e2e_ctx: E2EContext) -> None:
        assert e2e_ctx.token
        payload = {
            "product_name": f"E2E Maize {e2e_ctx.run_id}",
            "category": "Grains",
            "unit": "kg",
            "description": "E2E test product",
        }
        resp = _request_with_retry(
            e2e_ctx.client,
            "POST",
            "/stock/products",
            headers=_auth_headers(e2e_ctx.token),
            json=payload,
        )

        def _product_created(r: httpx.Response) -> bool:
            body = r.json()
            e2e_ctx.product_id = body.get("product_id")
            return (
                e2e_ctx.product_id is not None
                and body.get("product_name") == payload["product_name"]
            )

        _record(
            e2e_ctx,
            "CREATE product",
            "POST",
            "/stock/products",
            resp,
            expect_status=201,
            check=_product_created,
        )

    def test_05_list_farmers_and_products(self, e2e_ctx: E2EContext) -> None:
        assert e2e_ctx.token and e2e_ctx.farmer_id and e2e_ctx.product_id

        farmers_resp = _request_with_retry(
            e2e_ctx.client,
            "GET",
            "/stock/farmers",
            headers=_auth_headers(e2e_ctx.token),
        )

        def _farmer_in_list(r: httpx.Response) -> bool:
            ids = [f["farmer_id"] for f in r.json()]
            return e2e_ctx.farmer_id in ids

        _record(
            e2e_ctx,
            "READ farmers list",
            "GET",
            "/stock/farmers",
            farmers_resp,
            expect_status=200,
            check=_farmer_in_list,
        )

        products_resp = _request_with_retry(
            e2e_ctx.client,
            "GET",
            "/stock/products",
            headers=_auth_headers(e2e_ctx.token),
        )

        def _product_in_list(r: httpx.Response) -> bool:
            ids = [p["product_id"] for p in r.json()]
            return e2e_ctx.product_id in ids

        _record(
            e2e_ctx,
            "READ products list",
            "GET",
            "/stock/products",
            products_resp,
            expect_status=200,
            check=_product_in_list,
        )

    def test_06_create_stock_in(self, e2e_ctx: E2EContext) -> None:
        assert e2e_ctx.token and e2e_ctx.farmer_id and e2e_ctx.product_id
        payload = {
            "farmer_id": e2e_ctx.farmer_id,
            "product_id": e2e_ctx.product_id,
            "quantity": 50.0,
            "unit": "kg",
            "reference_note": f"E2E harvest {e2e_ctx.run_id}",
        }
        resp = _request_with_retry(
            e2e_ctx.client,
            "POST",
            "/stock/in",
            headers=_auth_headers(e2e_ctx.token),
            json=payload,
        )

        def _tx_created(r: httpx.Response) -> bool:
            body = r.json()
            e2e_ctx.transaction_id = body.get("transaction_id")
            return (
                e2e_ctx.transaction_id is not None
                and body.get("transaction_type") == "STOCK_IN"
                and body.get("quantity") == 50.0
            )

        _record(
            e2e_ctx,
            "CREATE stock-in (send)",
            "POST",
            "/stock/in",
            resp,
            expect_status=201,
            check=_tx_created,
        )

    def test_07_retrieve_balance_and_transactions(self, e2e_ctx: E2EContext) -> None:
        assert e2e_ctx.token and e2e_ctx.farmer_id and e2e_ctx.product_id

        balance_resp = _request_with_retry(
            e2e_ctx.client,
            "GET",
            f"/stock/current/{e2e_ctx.farmer_id}/{e2e_ctx.product_id}",
            headers=_auth_headers(e2e_ctx.token),
        )

        def _balance_ok(r: httpx.Response) -> bool:
            body = r.json()
            return body.get("current_stock") == 50.0

        _record(
            e2e_ctx,
            "RETRIEVE balance by id",
            "GET",
            f"/stock/current/{e2e_ctx.farmer_id}/{e2e_ctx.product_id}",
            balance_resp,
            expect_status=200,
            check=_balance_ok,
        )

        tx_resp = _request_with_retry(
            e2e_ctx.client,
            "GET",
            f"/stock/transactions?farmer_id={e2e_ctx.farmer_id}&product_id={e2e_ctx.product_id}",
            headers=_auth_headers(e2e_ctx.token),
        )

        def _tx_in_history(r: httpx.Response) -> bool:
            txs = r.json()
            return any(t.get("transaction_id") == e2e_ctx.transaction_id for t in txs)

        _record(
            e2e_ctx,
            "RETRIEVE transactions",
            "GET",
            "/stock/transactions",
            tx_resp,
            expect_status=200,
            check=_tx_in_history,
        )

    def test_08_update_via_adjustment(self, e2e_ctx: E2EContext) -> None:
        """Stock API has no PUT/PATCH; adjustment POST updates inventory balance."""
        assert e2e_ctx.token and e2e_ctx.farmer_id and e2e_ctx.product_id
        payload = {
            "farmer_id": e2e_ctx.farmer_id,
            "product_id": e2e_ctx.product_id,
            "quantity": 10.0,
            "unit": "kg",
            "reference_note": f"E2E adjustment {e2e_ctx.run_id}",
            "transaction_type": "ADJUSTMENT",
        }
        resp = _request_with_retry(
            e2e_ctx.client,
            "POST",
            "/stock/adjustment",
            headers=_auth_headers(e2e_ctx.token),
            json=payload,
        )

        def _adjustment_ok(r: httpx.Response) -> bool:
            return r.json().get("transaction_type") == "ADJUSTMENT"

        _record(
            e2e_ctx,
            "UPDATE via adjustment",
            "POST",
            "/stock/adjustment",
            resp,
            expect_status=201,
            check=_adjustment_ok,
        )

        balance_resp = _request_with_retry(
            e2e_ctx.client,
            "GET",
            f"/stock/current/{e2e_ctx.farmer_id}/{e2e_ctx.product_id}",
            headers=_auth_headers(e2e_ctx.token),
        )

        def _updated_balance(r: httpx.Response) -> bool:
            return r.json().get("current_stock") == 60.0  # 50 + 10 adjustment

        _record(
            e2e_ctx,
            "VERIFY updated balance",
            "GET",
            f"/stock/current/{e2e_ctx.farmer_id}/{e2e_ctx.product_id}",
            balance_resp,
            expect_status=200,
            check=_updated_balance,
        )

    def test_09_gateway_status(self, e2e_ctx: E2EContext) -> None:
        assert e2e_ctx.token
        resp = _request_with_retry(
            e2e_ctx.client,
            "GET",
            "/v1/status",
            headers=_auth_headers(e2e_ctx.token),
        )
        _record(
            e2e_ctx,
            "Gateway status",
            "GET",
            "/v1/status",
            resp,
            expect_status=200,
        )
