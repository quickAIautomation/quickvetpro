"""
Sistema de Alertas e Monitoramento
==================================

Detecta e notifica sobre erros críticos e anomalias:
- Erros 5xx frequentes
- Rate limit excedido repetidamente
- Falhas de integração (Stripe, WhatsApp, OpenAI)
- Quota de mensagens excedida
- Anomalias de uso

Notificações via:
- Webhook (n8n, Slack, Discord)
- Email (via n8n)
- Log estruturado
"""
import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass, asdict
import httpx

from app.infra.db import get_db_connection
from app.infra.redis import get_redis_client

logger = logging.getLogger(__name__)

# Configurações
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")  # Webhook para alertas
ALERT_COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "15"))
ALERT_REDIS_PREFIX = "quickvet:alert:"


class AlertSeverity(str, Enum):
    """Níveis de severidade"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertType(str, Enum):
    """Tipos de alerta"""
    ERROR_RATE_HIGH = "error_rate_high"
    RATE_LIMIT_ABUSE = "rate_limit_abuse"
    INTEGRATION_FAILURE = "integration_failure"
    QUOTA_EXCEEDED = "quota_exceeded"
    PAYMENT_FAILED = "payment_failed"
    SECURITY_ALERT = "security_alert"
    PERFORMANCE_DEGRADATION = "performance_degradation"
    SERVICE_DOWN = "service_down"
    ANOMALY_DETECTED = "anomaly_detected"


@dataclass
class Alert:
    """Estrutura de um alerta"""
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    metadata: Dict[str, Any] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict:
        return {
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat()
        }


class AlertService:
    """
    Serviço de alertas e monitoramento.
    
    Features:
    - Cooldown para evitar spam de alertas repetidos
    - Persistência no banco para histórico
    - Webhook para notificações externas
    - Agregação de alertas similares
    """
    
    def __init__(self):
        self.webhook_url = ALERT_WEBHOOK_URL
        self.cooldown_minutes = ALERT_COOLDOWN_MINUTES
    
    async def _get_redis(self):
        return get_redis_client()
    
    async def _is_in_cooldown(self, alert_type: str, identifier: str = "") -> bool:
        """Verifica se um tipo de alerta está em cooldown"""
        redis = await self._get_redis()
        key = f"{ALERT_REDIS_PREFIX}cooldown:{alert_type}:{identifier}"
        return await redis.exists(key)
    
    async def _set_cooldown(self, alert_type: str, identifier: str = ""):
        """Define cooldown para um tipo de alerta"""
        redis = await self._get_redis()
        key = f"{ALERT_REDIS_PREFIX}cooldown:{alert_type}:{identifier}"
        await redis.setex(key, self.cooldown_minutes * 60, "1")
    
    async def send_alert(self, alert: Alert, force: bool = False) -> bool:
        """
        Envia um alerta.
        
        Args:
            alert: Objeto Alert
            force: Se True, ignora cooldown
            
        Returns:
            True se enviado com sucesso
        """
        identifier = alert.metadata.get("identifier", "")
        
        # Verificar cooldown (exceto para CRITICAL ou force)
        if not force and alert.severity != AlertSeverity.CRITICAL:
            if await self._is_in_cooldown(alert.alert_type.value, identifier):
                logger.debug(f"Alerta {alert.alert_type.value} em cooldown")
                return False
        
        try:
            # Persistir no banco
            await self._save_to_db(alert)
            
            # Logar
            log_method = getattr(logger, alert.severity.value, logger.info)
            log_method(
                f"ALERTA [{alert.severity.value.upper()}] {alert.title}: {alert.message}",
                extra={"alert": alert.to_dict()}
            )
            
            # Enviar webhook
            if self.webhook_url:
                await self._send_webhook(alert)
            
            # Definir cooldown
            await self._set_cooldown(alert.alert_type.value, identifier)
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao enviar alerta: {e}")
            return False
    
    async def _save_to_db(self, alert: Alert):
        """Salva alerta no banco de dados"""
        try:
            db = await get_db_connection()
            await db.execute("""
                INSERT INTO alerts (alert_type, severity, title, message, metadata, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, 
                alert.alert_type.value,
                alert.severity.value,
                alert.title,
                alert.message,
                json.dumps(alert.metadata),
                alert.timestamp
            )
        except Exception as e:
            logger.error(f"Erro ao salvar alerta no banco: {e}")
    
    async def _send_webhook(self, alert: Alert):
        """Envia alerta via webhook"""
        try:
            payload = {
                "event": "alert",
                **alert.to_dict()
            }
            
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                logger.info(f"Alerta enviado via webhook: {alert.alert_type.value}")
                
        except Exception as e:
            logger.error(f"Erro ao enviar alerta via webhook: {e}")
    
    # ==================== ALERTAS ESPECÍFICOS ====================
    
    async def alert_high_error_rate(self, error_count: int, total_requests: int, period_minutes: int = 5):
        """Alerta para taxa de erro alta"""
        error_rate = (error_count / total_requests * 100) if total_requests > 0 else 0
        
        severity = AlertSeverity.WARNING if error_rate < 10 else AlertSeverity.ERROR
        if error_rate >= 25:
            severity = AlertSeverity.CRITICAL
        
        alert = Alert(
            alert_type=AlertType.ERROR_RATE_HIGH,
            severity=severity,
            title="Taxa de Erro Alta Detectada",
            message=f"Taxa de erro: {error_rate:.1f}% ({error_count} erros em {total_requests} requests nos últimos {period_minutes} minutos)",
            metadata={
                "error_count": error_count,
                "total_requests": total_requests,
                "error_rate": round(error_rate, 2),
                "period_minutes": period_minutes
            }
        )
        
        await self.send_alert(alert)
    
    async def alert_rate_limit_abuse(self, ip: str, endpoint: str, attempts: int):
        """Alerta para abuso de rate limit"""
        alert = Alert(
            alert_type=AlertType.RATE_LIMIT_ABUSE,
            severity=AlertSeverity.WARNING,
            title="Possível Abuso de Rate Limit",
            message=f"IP {ip} excedeu rate limit {attempts} vezes em {endpoint}",
            metadata={
                "ip": ip,
                "endpoint": endpoint,
                "attempts": attempts,
                "identifier": ip
            }
        )
        
        await self.send_alert(alert)
    
    async def alert_integration_failure(self, service: str, error: str, context: Dict = None):
        """Alerta para falha de integração"""
        severity = AlertSeverity.ERROR
        if service in ["stripe", "whatsapp"]:
            severity = AlertSeverity.CRITICAL
        
        alert = Alert(
            alert_type=AlertType.INTEGRATION_FAILURE,
            severity=severity,
            title=f"Falha de Integração: {service}",
            message=f"Erro ao comunicar com {service}: {error}",
            metadata={
                "service": service,
                "error": error,
                "context": context or {},
                "identifier": service
            }
        )
        
        await self.send_alert(alert)
    
    async def alert_quota_exceeded(self, user_id: str, quota_type: str, current: int, limit: int):
        """Alerta para quota excedida"""
        alert = Alert(
            alert_type=AlertType.QUOTA_EXCEEDED,
            severity=AlertSeverity.INFO,
            title="Quota Excedida",
            message=f"Usuário {user_id} excedeu quota de {quota_type}: {current}/{limit}",
            metadata={
                "user_id": user_id,
                "quota_type": quota_type,
                "current": current,
                "limit": limit,
                "identifier": user_id
            }
        )
        
        await self.send_alert(alert)
    
    async def alert_payment_failed(self, account_id: str, amount: int, reason: str):
        """Alerta para pagamento falho"""
        alert = Alert(
            alert_type=AlertType.PAYMENT_FAILED,
            severity=AlertSeverity.WARNING,
            title="Pagamento Falhou",
            message=f"Pagamento de R$ {amount/100:.2f} falhou para conta {account_id}: {reason}",
            metadata={
                "account_id": account_id,
                "amount_cents": amount,
                "reason": reason,
                "identifier": account_id
            }
        )
        
        await self.send_alert(alert)
    
    async def alert_security(self, event_type: str, details: str, ip: str = None, user_id: str = None):
        """Alerta de segurança"""
        alert = Alert(
            alert_type=AlertType.SECURITY_ALERT,
            severity=AlertSeverity.CRITICAL,
            title=f"Alerta de Segurança: {event_type}",
            message=details,
            metadata={
                "event_type": event_type,
                "ip": ip,
                "user_id": user_id,
                "identifier": ip or user_id or event_type
            }
        )
        
        await self.send_alert(alert, force=True)  # Segurança sempre força
    
    async def alert_performance(self, endpoint: str, avg_response_ms: float, threshold_ms: float):
        """Alerta para degradação de performance"""
        alert = Alert(
            alert_type=AlertType.PERFORMANCE_DEGRADATION,
            severity=AlertSeverity.WARNING,
            title="Degradação de Performance",
            message=f"Endpoint {endpoint} com tempo médio de {avg_response_ms:.0f}ms (limite: {threshold_ms:.0f}ms)",
            metadata={
                "endpoint": endpoint,
                "avg_response_ms": round(avg_response_ms, 2),
                "threshold_ms": threshold_ms,
                "identifier": endpoint
            }
        )
        
        await self.send_alert(alert)
    
    # ==================== CONSULTAS ====================
    
    async def get_recent_alerts(
        self,
        limit: int = 50,
        severity: Optional[AlertSeverity] = None,
        alert_type: Optional[AlertType] = None,
        include_acknowledged: bool = False
    ) -> List[Dict]:
        """Retorna alertas recentes"""
        try:
            db = await get_db_connection()
            
            query = "SELECT * FROM alerts WHERE 1=1"
            params = []
            param_count = 0
            
            if not include_acknowledged:
                query += " AND is_acknowledged = false"
            
            if severity:
                param_count += 1
                query += f" AND severity = ${param_count}"
                params.append(severity.value)
            
            if alert_type:
                param_count += 1
                query += f" AND alert_type = ${param_count}"
                params.append(alert_type.value)
            
            param_count += 1
            query += f" ORDER BY created_at DESC LIMIT ${param_count}"
            params.append(limit)
            
            rows = await db.fetch(query, *params)
            
            return [dict(row) for row in rows]
            
        except Exception as e:
            logger.error(f"Erro ao buscar alertas: {e}")
            return []
    
    async def acknowledge_alert(self, alert_id: int, acknowledged_by: str) -> bool:
        """Marca um alerta como reconhecido"""
        try:
            db = await get_db_connection()
            await db.execute("""
                UPDATE alerts 
                SET is_acknowledged = true, acknowledged_by = $1, acknowledged_at = $2
                WHERE alert_id = $3
            """, acknowledged_by, datetime.utcnow(), alert_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao reconhecer alerta: {e}")
            return False
    
    async def get_alert_stats(self, hours: int = 24) -> Dict:
        """Retorna estatísticas de alertas"""
        try:
            db = await get_db_connection()
            since = datetime.utcnow() - timedelta(hours=hours)
            
            # Total por severidade
            by_severity = await db.fetch("""
                SELECT severity, COUNT(*) as count
                FROM alerts
                WHERE created_at >= $1
                GROUP BY severity
            """, since)
            
            # Total por tipo
            by_type = await db.fetch("""
                SELECT alert_type, COUNT(*) as count
                FROM alerts
                WHERE created_at >= $1
                GROUP BY alert_type
                ORDER BY count DESC
            """, since)
            
            # Não reconhecidos
            unacknowledged = await db.fetchval("""
                SELECT COUNT(*) FROM alerts
                WHERE is_acknowledged = false AND created_at >= $1
            """, since)
            
            return {
                "period_hours": hours,
                "by_severity": {row["severity"]: row["count"] for row in by_severity},
                "by_type": {row["alert_type"]: row["count"] for row in by_type},
                "unacknowledged_count": unacknowledged
            }
            
        except Exception as e:
            logger.error(f"Erro ao obter estatísticas de alertas: {e}")
            return {}


# Instância global
alert_service = AlertService()


# ==================== MONITOR AUTOMÁTICO ====================

class AlertMonitor:
    """
    Monitor automático que verifica métricas e dispara alertas.
    Roda em background periodicamente.
    """
    
    def __init__(self):
        self.running = False
        self.check_interval = 60  # segundos
    
    async def start(self):
        """Inicia o monitor em background"""
        self.running = True
        logger.info("Alert Monitor iniciado")
        
        while self.running:
            try:
                await self._check_metrics()
            except Exception as e:
                logger.error(f"Erro no Alert Monitor: {e}")
            
            await asyncio.sleep(self.check_interval)
    
    def stop(self):
        """Para o monitor"""
        self.running = False
        logger.info("Alert Monitor parado")
    
    async def _check_metrics(self):
        """Verifica métricas e dispara alertas se necessário"""
        from app.middleware.observability import metrics
        
        stats = metrics.get_stats()
        
        # Verificar taxa de erro
        if stats["total_requests"] > 100:  # Só verifica se tiver requests suficientes
            error_rate = stats.get("error_rate", 0)
            if error_rate >= 5:
                await alert_service.alert_high_error_rate(
                    error_count=stats["total_errors"],
                    total_requests=stats["total_requests"],
                    period_minutes=5
                )
        
        # Verificar tempo de resposta
        avg_response = stats.get("avg_response_time_ms", 0)
        if avg_response > 2000:  # Mais de 2 segundos
            await alert_service.alert_performance(
                endpoint="global",
                avg_response_ms=avg_response,
                threshold_ms=2000
            )


# Instância do monitor
alert_monitor = AlertMonitor()
