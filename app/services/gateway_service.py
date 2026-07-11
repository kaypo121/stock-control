import asyncio
import hashlib
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import (
    APP_VERSION,
    DATA_PROCESSED_DIR,
    GATEWAY_CACHE_TTL_SECONDS,
    GATEWAY_FILE_SIZE_LIMIT_BYTES,
    GATEWAY_SUPPORTED_FILE_TYPES,
    GATEWAY_UPLOAD_DIR,
)
from app.database import SessionLocal
from app.models.gateway_models import (
    GatewayAuditLog,
    GatewayDeadLetter,
    GatewayEvent,
    GatewayFileAsset,
)
from app.models.gateway_models import GatewayPlugin as GatewayPluginModel
from app.models.gateway_models import (
    GatewayRequestLog,
    GatewaySession,
    GatewayTask,
    GatewayWebhookDelivery,
    GatewayWebhookEndpoint,
)
from app.models.integration_models import DataIntegrationSession, IntegrationReport
from app.models.quality_models import (
    FreshnessLevel,
    GradeClassification,
    HealthStatus,
    ProductCategory,
    PurchaseRecommendation,
    QualityAssessment,
    RipenessLevel,
    RiskLevel,
)
from app.repositories.stock_repo import StockRepository
from app.schemas.gateway_schemas import GatewayRequestEnvelope
from app.services.ai_provider_service import provider_service
from app.services.gateway_security import GatewayAPIError, utcnow
from app.exceptions import ExternalDependencyError
from app.services.integration_service import DataIntegrationService
from app.services.quality_service import QualityAssessmentService
from app.services.stock_service import StockService


def json_dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def json_loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def serialize_datetime(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize_datetime(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_datetime(item) for key, item in value.items()}
    return value


class CacheService:
    def __init__(self) -> None:
        self._memory_store: Dict[str, Tuple[float, Any]] = {}
        self._redis_client = None
        try:
            redis_url = os.getenv("REDIS_URL")
            if redis_url:
                import redis

                self._redis_client = redis.Redis.from_url(
                    redis_url, decode_responses=True
                )
        except ImportError:
            # Redis library not installed — fall back to in-memory cache
            self._redis_client = None
        except Exception as exc:  # pragma: no cover - unexpected runtime failures
            # Wrap unexpected external dependency errors to make handling explicit
            self._redis_client = None
            raise ExternalDependencyError("Failed to initialize redis client", details=str(exc)) from exc

    def get(self, key: str) -> Any:
        if self._redis_client:
            raw = self._redis_client.get(key)
            return json_loads(raw, None) if raw else None
        record = self._memory_store.get(key)
        if not record:
            return None
        expires_at, value = record
        if expires_at < time.time():
            self._memory_store.pop(key, None)
            return None
        return value

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int = GATEWAY_CACHE_TTL_SECONDS,
    ) -> None:
        encoded = json_dumps(serialize_datetime(value))
        if self._redis_client:
            self._redis_client.setex(key, ttl_seconds, encoded)
            return
        self._memory_store[key] = (
            time.time() + ttl_seconds,
            json.loads(encoded),
        )

    def delete(self, key: str) -> None:
        if self._redis_client:
            self._redis_client.delete(key)
        self._memory_store.pop(key, None)

    def health(self) -> Dict[str, Any]:
        if self._redis_client:
            try:
                return {
                    "backend": "redis",
                    "status": "healthy",
                    "ping": bool(self._redis_client.ping()),
                }
            except Exception as exc:
                return {
                    "backend": "redis",
                    "status": "degraded",
                    "detail": str(exc),
                }
        return {
            "backend": "memory",
            "status": "healthy",
            "entries": len(self._memory_store),
        }


cache_service = CacheService()


class GatewayPlugin:
    plugin_key = "base"
    name = "Base Plugin"
    version = "1.0.0"
    capabilities: List[str] = []

    def supports(self, module: str) -> bool:
        return False

    def execute(
        self,
        db: Session,
        request: GatewayRequestEnvelope,
        identity: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        raise NotImplementedError


class StockGatewayPlugin(GatewayPlugin):
    plugin_key = "stock"
    name = "Stock Gateway Plugin"
    version = "1.0.0"
    capabilities = [
        "inventory.snapshot",
        "inventory.low_stock",
        "transactions.list",
        "movement.create",
        "farmers.list",
        "products.list",
        "warehouses.list",
    ]

    def supports(self, module: str) -> bool:
        return module == "stock"

    def execute(
        self,
        db: Session,
        request: GatewayRequestEnvelope,
        identity: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        repo = StockRepository(db)
        service = StockService(db)
        resource = request.action.resource
        operation = request.action.operation
        payload = request.payload
        if resource == "inventory" and operation == "snapshot":
            balances = repo.get_all_balances()
            return {
                "balances": [
                    {
                        "balanceId": balance.balance_id,
                        "farmerId": balance.farmer_id,
                        "farmerName": (
                            balance.farmer.full_name if balance.farmer else None
                        ),
                        "productId": balance.product_id,
                        "productName": (
                            balance.product.product_name if balance.product else None
                        ),
                        "warehouseId": balance.warehouse_id,
                        "warehouseName": (
                            balance.warehouse.warehouse_name
                            if balance.warehouse
                            else None
                        ),
                        "currentStock": balance.current_stock,
                        "reorderLevel": balance.reorder_level,
                        "lastUpdated": balance.last_updated.isoformat(),
                    }
                    for balance in balances
                ]
            }
        if resource == "inventory" and operation == "low_stock":
            balances = repo.get_all_balances()
            return {
                "items": [
                    {
                        "farmerName": (
                            balance.farmer.full_name if balance.farmer else None
                        ),
                        "productName": (
                            balance.product.product_name if balance.product else None
                        ),
                        "warehouseName": (
                            balance.warehouse.warehouse_name
                            if balance.warehouse
                            else None
                        ),
                        "currentStock": balance.current_stock,
                        "reorderLevel": balance.reorder_level,
                    }
                    for balance in balances
                    if balance.current_stock <= balance.reorder_level
                ]
            }
        if resource == "transactions" and operation == "list":
            limit = int(payload.get("limit", 100))
            txs = repo.get_transactions(
                farmer_id=payload.get("farmer_id"),
                product_id=payload.get("product_id"),
                warehouse_id=payload.get("warehouse_id"),
                limit=limit,
            )
            return {
                "transactions": [
                    {
                        "transactionId": tx.transaction_id,
                        "farmerId": tx.farmer_id,
                        "productId": tx.product_id,
                        "warehouseId": tx.warehouse_id,
                        "transactionType": tx.transaction_type,
                        "quantity": tx.quantity,
                        "unit": tx.unit,
                        "transactionDate": tx.transaction_date.isoformat(),
                        "referenceNote": tx.reference_note,
                    }
                    for tx in txs
                ]
            }
        if resource == "movement" and operation == "create":
            tx = service.record_movement(
                farmer_id=payload["farmer_id"],
                product_id=payload["product_id"],
                warehouse_id=payload.get("warehouse_id"),
                transaction_type=payload["transaction_type"],
                quantity=payload["quantity"],
                unit=payload["unit"],
                transaction_date=payload.get("transaction_date"),
                reference_note=payload.get("reference_note"),
            )
            return {
                "transaction": {
                    "transactionId": tx.transaction_id,
                    "transactionType": tx.transaction_type,
                    "quantity": tx.quantity,
                    "unit": tx.unit,
                    "transactionDate": tx.transaction_date.isoformat(),
                }
            }
        if resource == "farmers" and operation == "list":
            records = repo.get_all_farmers(
                skip=int(payload.get("skip", 0)),
                limit=int(payload.get("limit", 100)),
            )
            return {
                "farmers": [
                    {
                        "farmerId": item.farmer_id,
                        "fullName": item.full_name,
                        "region": item.region,
                    }
                    for item in records
                ]
            }
        if resource == "products" and operation == "list":
            records = repo.get_all_products(
                skip=int(payload.get("skip", 0)),
                limit=int(payload.get("limit", 100)),
            )
            return {
                "products": [
                    {
                        "productId": item.product_id,
                        "productName": item.product_name,
                        "unit": item.unit,
                    }
                    for item in records
                ]
            }
        if resource == "warehouses" and operation == "list":
            records = repo.get_all_warehouses()
            return {
                "warehouses": [
                    {
                        "warehouseId": item.warehouse_id,
                        "warehouseName": item.warehouse_name,
                        "region": item.region,
                    }
                    for item in records
                ]
            }
        raise GatewayAPIError(
            status.HTTP_404_NOT_FOUND,
            "ROUTE_NOT_FOUND",
            "Unsupported stock action.",
        )


class QualityGatewayPlugin(GatewayPlugin):
    plugin_key = "quality"
    name = "Quality Gateway Plugin"
    version = "1.0.0"
    capabilities = [
        "assessments.list",
        "assessments.summary",
        "reference.categories",
    ]

    def supports(self, module: str) -> bool:
        return module == "quality"

    def execute(
        self,
        db: Session,
        request: GatewayRequestEnvelope,
        identity: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        resource = request.action.resource
        operation = request.action.operation
        payload = request.payload
        service = QualityAssessmentService(db)
        if resource == "assessments" and operation == "list":
            records = service.list_assessments(
                product_name=payload.get("product_name"),
                category=payload.get("category"),
                farmer_id=payload.get("farmer_id"),
                recommendation=payload.get("recommendation"),
                skip=int(payload.get("skip", 0)),
                limit=int(payload.get("limit", 50)),
            )
            return {
                "assessments": [
                    {
                        "assessmentId": record.assessment_id,
                        "productName": record.product_name,
                        "category": record.category,
                        "farmerSupplier": record.farmer_supplier,
                        "qualityScore": record.quality_score,
                        "gradeClassification": record.grade_classification,
                        "purchaseRecommendation": record.purchase_recommendation,
                        "assessmentDate": record.assessment_date.isoformat(),
                    }
                    for record in records
                ]
            }
        if resource == "assessments" and operation == "summary":
            category = payload.get("category")
            query = db.query(
                QualityAssessment.product_name,
                QualityAssessment.category,
                func.count(QualityAssessment.assessment_id).label("total"),
                func.avg(QualityAssessment.quality_score).label("avg_quality"),
                func.avg(QualityAssessment.market_readiness_score).label(
                    "avg_readiness"
                ),
                func.avg(QualityAssessment.estimated_market_value).label("avg_value"),
            )
            if category:
                query = query.filter(QualityAssessment.category == category)
            rows = query.group_by(
                QualityAssessment.product_name, QualityAssessment.category
            ).all()
            return {
                "summary": [
                    {
                        "productName": row.product_name,
                        "category": row.category,
                        "totalAssessments": row.total,
                        "averageQualityScore": round(row.avg_quality or 0, 2),
                        "averageMarketReadiness": round(row.avg_readiness or 0, 2),
                        "averageMarketValueGhs": round(row.avg_value or 0, 2),
                    }
                    for row in rows
                ]
            }
        if resource == "reference" and operation == "categories":
            return {
                "categories": [item.value for item in ProductCategory],
                "gradeClassifications": [item.value for item in GradeClassification],
                "riskLevels": [item.value for item in RiskLevel],
                "recommendations": [item.value for item in PurchaseRecommendation],
                "ripenessLevels": [item.value for item in RipenessLevel],
                "healthStatuses": [item.value for item in HealthStatus],
                "freshnessLevels": [item.value for item in FreshnessLevel],
            }
        raise GatewayAPIError(
            status.HTTP_404_NOT_FOUND,
            "ROUTE_NOT_FOUND",
            "Unsupported quality action.",
        )


class IntegrationGatewayPlugin(GatewayPlugin):
    plugin_key = "integration"
    name = "Integration Gateway Plugin"
    version = "1.0.0"
    capabilities = ["sessions.list", "reports.standalone", "health.overview"]

    def supports(self, module: str) -> bool:
        return module == "integration"

    def execute(
        self,
        db: Session,
        request: GatewayRequestEnvelope,
        identity: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        resource = request.action.resource
        operation = request.action.operation
        payload = request.payload
        service = DataIntegrationService(db)
        if resource == "sessions" and operation == "list":
            records = service.list_sessions(
                skip=int(payload.get("skip", 0)),
                limit=int(payload.get("limit", 50)),
            )
            return {
                "sessions": [
                    {
                        "sessionId": item.session_id,
                        "fileName": item.file_name,
                        "status": item.status,
                        "totalRows": item.total_rows,
                        "transactionsInserted": item.transactions_inserted,
                        "startedAt": (
                            item.started_at.isoformat() if item.started_at else None
                        ),
                        "completedAt": (
                            item.completed_at.isoformat() if item.completed_at else None
                        ),
                    }
                    for item in records
                ]
            }
        if resource == "reports" and operation == "standalone":
            return service.get_standalone_reports()
        if resource == "health" and operation == "overview":
            session_count = (
                db.query(func.count(DataIntegrationSession.session_id)).scalar() or 0
            )
            report_count = (
                db.query(func.count(IntegrationReport.report_id)).scalar() or 0
            )
            return {
                "sessions": session_count,
                "reports": report_count,
                "latestStatus": (
                    db.query(DataIntegrationSession.status)
                    .order_by(DataIntegrationSession.started_at.desc())
                    .limit(1)
                    .scalar()
                )
                or "UNKNOWN",
            }
        raise GatewayAPIError(
            status.HTTP_404_NOT_FOUND,
            "ROUTE_NOT_FOUND",
            "Unsupported integration action.",
        )


class SystemGatewayPlugin(GatewayPlugin):
    plugin_key = "system"
    name = "System Gateway Plugin"
    version = "1.0.0"
    capabilities = [
        "context.echo",
        "providers.catalog",
        "models.list",
        "plugins.list",
    ]

    def supports(self, module: str) -> bool:
        return module in {"system", "gateway"}

    def execute(
        self,
        db: Session,
        request: GatewayRequestEnvelope,
        identity: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        resource = request.action.resource
        operation = request.action.operation
        if resource == "context" and operation == "echo":
            return serialize_datetime(request.context.model_dump(by_alias=True))
        if resource == "providers" and operation == "catalog":
            return {"providers": provider_service.catalog()}
        if resource == "models" and operation == "list":
            return {"providers": provider_service.model_catalog()}
        if resource == "plugins" and operation == "list":
            return {"plugins": plugin_registry.describe()}
        raise GatewayAPIError(
            status.HTTP_404_NOT_FOUND,
            "ROUTE_NOT_FOUND",
            "Unsupported system action.",
        )


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: List[GatewayPlugin] = [
            StockGatewayPlugin(),
            QualityGatewayPlugin(),
            IntegrationGatewayPlugin(),
            SystemGatewayPlugin(),
        ]

    def describe(self) -> List[Dict[str, Any]]:
        return [
            {
                "pluginKey": plugin.plugin_key,
                "name": plugin.name,
                "version": plugin.version,
                "enabled": True,
                "capabilities": plugin.capabilities,
            }
            for plugin in self._plugins
        ]

    def sync_models(self, db: Session) -> None:
        existing = {
            item.plugin_key: item for item in db.query(GatewayPluginModel).all()
        }
        for plugin in self._plugins:
            record = existing.get(plugin.plugin_key)
            if not record:
                db.add(
                    GatewayPluginModel(
                        plugin_key=plugin.plugin_key,
                        name=plugin.name,
                        version=plugin.version,
                        enabled=True,
                        config_json=json_dumps({"capabilities": plugin.capabilities}),
                    )
                )
            else:
                record.name = plugin.name
                record.version = plugin.version
                record.enabled = True
                record.config_json = json_dumps({"capabilities": plugin.capabilities})
        db.commit()

    def dispatch(
        self,
        db: Session,
        request: GatewayRequestEnvelope,
        identity: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        for plugin in self._plugins:
            if plugin.supports(request.action.module):
                return plugin.execute(db, request, identity)
        raise GatewayAPIError(
            status.HTTP_404_NOT_FOUND,
            "MODULE_NOT_FOUND",
            "No plugin could handle the requested module.",
        )


plugin_registry = PluginRegistry()


class GatewayEventService:
    def publish(
        self,
        db: Session,
        event_type: str,
        topic: str,
        source: str,
        payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> GatewayEvent:
        event = GatewayEvent(
            event_type=event_type,
            topic=topic,
            source=source,
            payload_json=json_dumps(payload),
            metadata_json=json_dumps(metadata or {}),
            trace_id=trace_id,
            request_id=request_id,
            correlation_id=correlation_id,
            status="PUBLISHED",
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event

    def list_events(self, db: Session, limit: int = 100) -> List[GatewayEvent]:
        return (
            db.query(GatewayEvent)
            .order_by(GatewayEvent.created_at.desc())
            .limit(limit)
            .all()
        )


class GatewayWebhookService:
    def register(self, db: Session, payload: Dict[str, Any]) -> GatewayWebhookEndpoint:
        endpoint = GatewayWebhookEndpoint(
            name=payload["name"],
            target_url=str(payload["targetUrl"]),
            event_types_json=json_dumps(payload["eventTypes"]),
            secret_key=payload["secretKey"],
            headers_json=json_dumps(payload.get("headers", {})),
            timeout_seconds=payload.get("timeoutSeconds", 10),
            max_retries=payload.get("maxRetries", 3),
            is_active=True,
        )
        db.add(endpoint)
        db.commit()
        db.refresh(endpoint)
        return endpoint

    def list_endpoints(self, db: Session) -> List[GatewayWebhookEndpoint]:
        return (
            db.query(GatewayWebhookEndpoint)
            .order_by(GatewayWebhookEndpoint.created_at.desc())
            .all()
        )

    async def dispatch_event(self, event_id: str) -> None:
        db = SessionLocal()
        try:
            event = (
                db.query(GatewayEvent).filter(GatewayEvent.event_id == event_id).first()
            )
            if not event:
                return
            endpoints = (
                db.query(GatewayWebhookEndpoint)
                .filter(GatewayWebhookEndpoint.is_active.is_(True))
                .all()
            )
            event_types = {event.event_type, event.topic}
            for endpoint in endpoints:
                subscribed = set(json_loads(endpoint.event_types_json, []))
                if not (event_types & subscribed):
                    continue
                delivery = GatewayWebhookDelivery(
                    endpoint_id=endpoint.id,
                    event_id=event.id,
                    status="PENDING",
                )
                db.add(delivery)
                db.commit()
                db.refresh(delivery)
                await self._send_delivery(db, delivery, endpoint, event)
            event.processed_at = utcnow()
            db.commit()
        finally:
            db.close()

    async def _send_delivery(
        self,
        db: Session,
        delivery: GatewayWebhookDelivery,
        endpoint: GatewayWebhookEndpoint,
        event: GatewayEvent,
    ) -> None:
        payload = {
            "eventId": event.event_id,
            "eventType": event.event_type,
            "topic": event.topic,
            "source": event.source,
            "traceId": event.trace_id,
            "requestId": event.request_id,
            "timestamp": event.created_at.isoformat(),
            "payload": json_loads(event.payload_json, {}),
            "metadata": json_loads(event.metadata_json, {}),
        }
        encoded = json_dumps(payload)
        signature = hashlib.sha256(
            f"{endpoint.secret_key}.{encoded}".encode("utf-8")
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Gateway-Signature": signature,
        }
        headers.update(json_loads(endpoint.headers_json, {}))
        try:
            async with httpx.AsyncClient(timeout=endpoint.timeout_seconds) as client:
                response = await client.post(
                    endpoint.target_url, content=encoded, headers=headers
                )
            delivery.attempt_count += 1
            delivery.response_status = response.status_code
            delivery.response_body = response.text[:2000]
            if 200 <= response.status_code < 300:
                delivery.status = "DELIVERED"
            else:
                delivery.status = "FAILED"
                delivery.last_error = response.text[:1000]
                await self._handle_retry(db, delivery, endpoint, payload)
        except Exception as exc:
            delivery.attempt_count += 1
            delivery.status = "FAILED"
            delivery.last_error = str(exc)
            await self._handle_retry(db, delivery, endpoint, payload)
        db.commit()

    async def _handle_retry(
        self,
        db: Session,
        delivery: GatewayWebhookDelivery,
        endpoint: GatewayWebhookEndpoint,
        payload: Dict[str, Any],
    ) -> None:
        if delivery.attempt_count <= endpoint.max_retries:
            delivery.next_retry_at = utcnow()
            return
        delivery.status = "DEAD_LETTER"
        db.add(
            GatewayDeadLetter(
                delivery_id=delivery.delivery_id,
                reason=delivery.last_error or "Webhook delivery failed.",
                payload_json=json_dumps(payload),
            )
        )


class GatewayTaskService:
    def create_task(
        self,
        db: Session,
        request: GatewayRequestEnvelope,
        identity: Optional[Dict[str, Any]],
        priority: str,
        task_type: str,
        trace_id: str,
        request_id: str,
    ) -> GatewayTask:
        task = GatewayTask(
            principal_id=identity["principal"].id if identity else None,
            task_type=task_type,
            module_name=request.action.module,
            action_name=f"{request.action.resource}.{request.action.operation}",
            status="QUEUED",
            priority=priority,
            progress=0.0,
            trace_id=trace_id,
            request_id=request_id,
            payload_json=request.model_dump_json(by_alias=True),
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    def get_task(self, db: Session, task_id: str) -> GatewayTask:
        task = db.query(GatewayTask).filter(GatewayTask.task_id == task_id).first()
        if not task:
            raise GatewayAPIError(
                status.HTTP_404_NOT_FOUND,
                "TASK_NOT_FOUND",
                "Task was not found.",
            )
        return task

    def cancel_task(self, db: Session, task_id: str) -> GatewayTask:
        task = self.get_task(db, task_id)
        if task.status in {"COMPLETED", "FAILED", "CANCELLED"}:
            return task
        task.status = "CANCELLED"
        task.progress = 0.0
        db.commit()
        db.refresh(task)
        return task

    def process_task_background(self, task_id: str) -> None:
        asyncio.run(self._process_task(task_id))

    async def _process_task(self, task_id: str) -> None:
        db = SessionLocal()
        try:
            task = db.query(GatewayTask).filter(GatewayTask.task_id == task_id).first()
            if not task or task.status == "CANCELLED":
                return
            task.status = "RUNNING"
            task.progress = 10.0
            task.started_at = utcnow()
            db.commit()

            request_payload = json.loads(task.payload_json)
            request = GatewayRequestEnvelope.model_validate(request_payload)
            result = gateway_orchestrator.process_gateway_request(
                db=db,
                request=request,
                http_method="BACKGROUND",
                path="/v1/tasks",
                identity=({"principal": task.principal} if task.principal else None),
                request_id=task.request_id or str(uuid.uuid4()),
                trace_id=task.trace_id or str(uuid.uuid4()),
                caller_ip="background",
                allow_duplicate=True,
            )
            task.status = "COMPLETED"
            task.progress = 100.0
            task.result_json = json_dumps(result)
            task.completed_at = utcnow()
            db.commit()
        except Exception as exc:
            if "task" in locals() and task:
                task.status = "FAILED"
                task.error_message = str(exc)
                task.completed_at = utcnow()
                task.progress = 100.0
                db.commit()
        finally:
            db.close()


class GatewayFileService:
    def __init__(self) -> None:
        Path(GATEWAY_UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(DATA_PROCESSED_DIR).mkdir(parents=True, exist_ok=True)

    async def store_file(
        self, db: Session, upload: UploadFile, principal_id: Optional[int]
    ) -> GatewayFileAsset:
        content = await upload.read()
        if len(content) > GATEWAY_FILE_SIZE_LIMIT_BYTES:
            raise GatewayAPIError(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "FILE_TOO_LARGE",
                "Uploaded file exceeds the configured size limit.",
                {"maxBytes": GATEWAY_FILE_SIZE_LIMIT_BYTES},
            )
        extension = Path(upload.filename or "").suffix.lower()
        if extension and extension not in GATEWAY_SUPPORTED_FILE_TYPES:
            raise GatewayAPIError(
                status.HTTP_400_BAD_REQUEST,
                "UNSUPPORTED_FILE",
                "File type is not supported by the gateway.",
            )
        file_id = str(uuid.uuid4())
        checksum = hashlib.sha256(content).hexdigest()
        storage_path = Path(GATEWAY_UPLOAD_DIR) / f"{file_id}{extension or '.bin'}"
        storage_path.write_bytes(content)
        asset = GatewayFileAsset(
            file_id=file_id,
            principal_id=principal_id,
            original_name=upload.filename or file_id,
            content_type=upload.content_type or "application/octet-stream",
            extension=extension or ".bin",
            size_bytes=len(content),
            checksum_sha256=checksum,
            storage_path=str(storage_path),
            metadata_json=json_dumps({"filename": upload.filename}),
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset

    def get_asset(self, db: Session, file_id: str) -> GatewayFileAsset:
        asset = (
            db.query(GatewayFileAsset)
            .filter(GatewayFileAsset.file_id == file_id)
            .first()
        )
        if not asset:
            raise GatewayAPIError(
                status.HTTP_404_NOT_FOUND,
                "FILE_NOT_FOUND",
                "File was not found.",
            )
        return asset


class GatewayMetricsService:
    def health(self, db: Session) -> Dict[str, Any]:
        # Probe DB availability; if tables are missing (e.g., during tests using alternate engines),
        # return degraded status with zeroed counters instead of raising.
        database_ok = True
        try:
            db.query(func.count(GatewayRequestLog.id)).scalar()
        except Exception:
            database_ok = False

        def safe_count(query_callable, default=0):
            if not database_ok:
                return default
            try:
                return query_callable() or default
            except Exception:
                return default

        requests_count = safe_count(
            lambda: db.query(func.count(GatewayRequestLog.id)).scalar()
        )
        events_count = safe_count(
            lambda: db.query(func.count(GatewayEvent.id)).scalar()
        )
        tasks_count = safe_count(lambda: db.query(func.count(GatewayTask.id)).scalar())
        queued_tasks = safe_count(
            lambda: db.query(func.count(GatewayTask.id))
            .filter(GatewayTask.status == "QUEUED")
            .scalar()
        )
        running_tasks = safe_count(
            lambda: db.query(func.count(GatewayTask.id))
            .filter(GatewayTask.status == "RUNNING")
            .scalar()
        )
        pending_webhook_retries = safe_count(
            lambda: db.query(func.count(GatewayWebhookDelivery.id))
            .filter(GatewayWebhookDelivery.status == "FAILED")
            .scalar()
        )
        dead_letters = safe_count(
            lambda: db.query(func.count(GatewayDeadLetter.id)).scalar()
        )

        return {
            "service": "agriculture-ai-gateway",
            "status": "healthy" if database_ok else "degraded",
            "version": APP_VERSION,
            "database": {
                "status": "healthy" if database_ok else "degraded",
                "requests": requests_count,
                "events": events_count,
                "tasks": tasks_count,
            },
            "cache": cache_service.health(),
            "queue": {
                "queuedTasks": queued_tasks,
                "runningTasks": running_tasks,
                "pendingWebhookRetries": pending_webhook_retries,
                "deadLetters": dead_letters,
            },
            "metrics": self.status(db),
        }

    def status(self, db: Session) -> Dict[str, Any]:
        try:
            import psutil

            process = psutil.Process()
            cpu = psutil.cpu_percent(interval=0.0)
            memory = process.memory_info().rss
        except Exception:
            cpu = 0.0
            memory = 0
        total_requests = db.query(func.count(GatewayRequestLog.id)).scalar() or 0
        error_requests = (
            db.query(func.count(GatewayRequestLog.id))
            .filter(GatewayRequestLog.success.is_(False))
            .scalar()
            or 0
        )
        avg_latency = (
            db.query(func.avg(GatewayRequestLog.processing_time_ms)).scalar() or 0.0
        )
        return {
            "requestCount": total_requests,
            "errorRate": (
                round((error_requests / total_requests), 4) if total_requests else 0.0
            ),
            "averageLatencyMs": round(avg_latency, 2),
            "auditLogCount": db.query(func.count(GatewayAuditLog.id)).scalar() or 0,
            "cpuPercent": cpu,
            "memoryBytes": memory,
        }


event_service = GatewayEventService()
webhook_service = GatewayWebhookService()
task_service = GatewayTaskService()
file_service = GatewayFileService()
metrics_service = GatewayMetricsService()


class GatewayOrchestrator:
    def bootstrap(self, db: Session) -> None:
        plugin_registry.sync_models(db)

    def required_permissions(self, request: GatewayRequestEnvelope) -> List[str]:
        module = request.action.module
        operation = request.action.operation.lower()
        if operation in {
            "snapshot",
            "list",
            "get",
            "summary",
            "catalog",
            "status",
            "echo",
            "overview",
            "categories",
        }:
            return [f"{module}:read", "gateway:read"]
        return [f"{module}:write", "gateway:write"]

    def upsert_context_session(
        self,
        db: Session,
        request: GatewayRequestEnvelope,
        identity: Optional[Dict[str, Any]],
        trace_id: str,
    ) -> GatewaySession:
        session_id = request.context.session_id or str(uuid.uuid4())
        record = (
            db.query(GatewaySession)
            .filter(GatewaySession.session_id == session_id)
            .first()
        )
        if not record:
            record = GatewaySession(session_id=session_id)
            db.add(record)
        record.principal_id = identity["principal"].id if identity else None
        record.conversation_id = request.context.conversation_id
        record.memory_id = request.context.memory_id
        record.workspace_id = request.context.workspace_id or (
            request.workspace.id if request.workspace else None
        )
        record.project_id = request.context.project_id
        record.organization_id = request.context.organization_id
        record.user_id = request.context.user_id or (
            request.user.id if request.user else None
        )
        record.agent_id = request.context.agent_id or (
            request.agent.id if request.agent else None
        )
        record.tool_id = request.context.tool_id
        record.correlation_id = request.context.correlation_id
        record.trace_id = request.context.trace_id or trace_id
        record.metadata_json = json_dumps(request.context.metadata)
        record.last_seen_at = utcnow()
        db.commit()
        db.refresh(record)
        return record

    def process_gateway_request(
        self,
        db: Session,
        request: GatewayRequestEnvelope,
        http_method: str,
        path: str,
        identity: Optional[Dict[str, Any]],
        request_id: str,
        trace_id: str,
        caller_ip: str,
        allow_duplicate: bool = False,
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        duplicate = (
            db.query(GatewayRequestLog)
            .filter(GatewayRequestLog.request_id == request_id)
            .first()
        )
        if duplicate and not allow_duplicate:
            duplicate_body = json_loads(duplicate.response_body, {})
            if duplicate.success and duplicate_body:
                return {"duplicate": True, "response": duplicate_body}
            raise GatewayAPIError(
                status.HTTP_409_CONFLICT,
                "DUPLICATE_REQUEST",
                "Request has already been processed.",
                {"requestId": request_id},
            )

        cache_key = None
        if request.action.mode == "sync" and request.action.operation.lower() in {
            "snapshot",
            "list",
            "get",
            "summary",
            "catalog",
            "categories",
            "overview",
        }:
            cache_key = hashlib.sha256(
                json_dumps(
                    {
                        "module": request.action.module,
                        "resource": request.action.resource,
                        "operation": request.action.operation,
                        "payload": request.payload,
                        "role": identity["role"] if identity else "anonymous",
                    }
                ).encode("utf-8")
            ).hexdigest()
            cached = cache_service.get(cache_key)
            if cached is not None:
                return {"cached": True, "response": cached}

        context_session = self.upsert_context_session(db, request, identity, trace_id)
        data = plugin_registry.dispatch(db, request, identity)
        response_payload = {
            "context": {
                "sessionId": context_session.session_id,
                "traceId": context_session.trace_id,
                "correlationId": context_session.correlation_id,
            },
            "result": serialize_datetime(data),
        }
        processing_ms = (time.perf_counter() - started) * 1000.0
        request_log = GatewayRequestLog(
            request_id=request_id,
            trace_id=trace_id,
            correlation_id=request.context.correlation_id,
            principal_id=identity["principal"].id if identity else None,
            http_method=http_method,
            path=path,
            module_name=request.action.module,
            action_name=f"{request.action.resource}.{request.action.operation}",
            request_body=request.model_dump_json(by_alias=True),
            response_body=json_dumps(response_payload),
            request_size_bytes=len(
                request.model_dump_json(by_alias=True).encode("utf-8")
            ),
            response_size_bytes=len(json_dumps(response_payload).encode("utf-8")),
            status_code=200,
            success=True,
            processing_time_ms=processing_ms,
            caller_ip=caller_ip,
            metadata_json=json_dumps(request.metadata),
        )
        db.add(request_log)
        db.add(
            GatewayAuditLog(
                principal_id=identity["principal"].id if identity else None,
                event_type="ACTION",
                severity="INFO",
                action=f"{request.action.module}.{request.action.resource}.{request.action.operation}",
                resource=request.action.module,
                result="SUCCESS",
                trace_id=trace_id,
                request_id=request_id,
                details_json=json_dumps({"mode": request.action.mode}),
            )
        )
        db.commit()
        if cache_key:
            cache_service.set(cache_key, response_payload)
        event = event_service.publish(
            db=db,
            event_type="gateway.request.completed",
            topic=f"{request.action.module}.{request.action.resource}",
            source="gateway",
            payload={
                "requestId": request_id,
                "traceId": trace_id,
                "module": request.action.module,
            },
            metadata={"status": "SUCCESS"},
            trace_id=trace_id,
            request_id=request_id,
            correlation_id=request.context.correlation_id,
        )
        return {"eventId": event.event_id, **response_payload}

    def log_failure(
        self,
        db: Session,
        request_id: str,
        trace_id: str,
        path: str,
        http_method: str,
        caller_ip: str,
        request_body: Optional[str],
        status_code_value: int,
        error_code: str,
        message: str,
        identity: Optional[Dict[str, Any]],
    ) -> None:
        db.add(
            GatewayRequestLog(
                request_id=request_id,
                trace_id=trace_id,
                correlation_id=None,
                principal_id=identity["principal"].id if identity else None,
                http_method=http_method,
                path=path,
                module_name=None,
                action_name=None,
                request_body=request_body,
                response_body=json_dumps({"error": message}),
                request_size_bytes=(
                    len(request_body.encode("utf-8")) if request_body else 0
                ),
                response_size_bytes=len(message.encode("utf-8")),
                status_code=status_code_value,
                success=False,
                processing_time_ms=0.0,
                error_code=error_code,
                caller_ip=caller_ip,
            )
        )
        db.commit()


gateway_orchestrator = GatewayOrchestrator()


def render_stream_chunks(content: Dict[str, Any]) -> List[str]:
    encoded = json_dumps(serialize_datetime(content))
    chunk_size = max(32, len(encoded) // 4)
    return [
        encoded[index : index + chunk_size]
        for index in range(0, len(encoded), chunk_size)
    ]
