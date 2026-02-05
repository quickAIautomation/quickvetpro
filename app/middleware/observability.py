"""
Middleware de Observabilidade para FastAPI
- Correlation ID em todas as requests
- Métricas de tempo de resposta
- Logging automático de requests
"""
import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.infra.logging_config import set_correlation_id, get_correlation_id, get_logger

logger = get_logger(__name__)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """
    Middleware que adiciona observabilidade a todas as requests:
    - Gera/propaga correlation_id
    - Mede tempo de resposta
    - Loga início e fim de requests
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Obter ou gerar correlation_id
        correlation_id = request.headers.get("X-Correlation-ID")
        if not correlation_id:
            correlation_id = str(uuid.uuid4())[:8]
        
        set_correlation_id(correlation_id)
        
        # Registrar início da request
        start_time = time.perf_counter()
        method = request.method
        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"
        
        logger.info(
            f"Request iniciada: {method} {path}",
            method=method,
            path=path,
            client_ip=client_ip,
            correlation_id=correlation_id
        )
        
        # Processar request
        try:
            response = await call_next(request)
            
            # Calcular tempo de resposta
            duration_ms = (time.perf_counter() - start_time) * 1000
            
            # Adicionar headers de observabilidade
            response.headers["X-Correlation-ID"] = correlation_id
            response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
            
            # Obter status code da resposta
            status_code = response.status_code
            
            # Registrar métricas
            metrics.record_request(path, duration_ms, status_code)
            
            # Logar conclusão
            log_level = "info" if status_code < 400 else "warning" if status_code < 500 else "error"
            
            getattr(logger, log_level)(
                f"Request concluída: {method} {path} - {status_code} ({duration_ms:.2f}ms)",
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=round(duration_ms, 2),
                correlation_id=correlation_id
            )
            
            # Disparar alerta se taxa de erro alta (verificar a cada 100 requests)
            if metrics.request_count % 100 == 0 and metrics.request_count > 0:
                error_rate = metrics.error_count / metrics.request_count * 100
                if error_rate >= 5:  # 5% de erro
                    try:
                        from app.services.alert_service import alert_service
                        await alert_service.alert_high_error_rate(
                            error_count=metrics.error_count,
                            total_requests=metrics.request_count,
                            period_minutes=5
                        )
                    except:
                        pass  # Não bloquear request se alerta falhar
            
            # Disparar alerta se performance degradada
            if duration_ms > 2000:  # Mais de 2 segundos
                try:
                    from app.services.alert_service import alert_service
                    await alert_service.alert_performance(
                        endpoint=path,
                        avg_response_ms=duration_ms,
                        threshold_ms=2000
                    )
                except:
                    pass
            
            return response
            
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            
            # Registrar erro nas métricas
            metrics.record_request(path, duration_ms, 500)
            
            logger.exception(
                f"Request falhou: {method} {path} - {str(e)}",
                method=method,
                path=path,
                error=str(e),
                duration_ms=round(duration_ms, 2),
                correlation_id=correlation_id
            )
            
            # Disparar alerta de erro crítico
            try:
                from app.services.alert_service import alert_service, AlertSeverity, AlertType
                from app.services.alert_service import Alert
                await alert_service.send_alert(Alert(
                    alert_type=AlertType.ERROR_RATE_HIGH,
                    severity=AlertSeverity.ERROR,
                    title="Erro em Request",
                    message=f"Erro 500 em {method} {path}: {str(e)[:200]}",
                    metadata={
                        "method": method,
                        "path": path,
                        "error": str(e),
                        "correlation_id": correlation_id
                    }
                ))
            except:
                pass  # Não bloquear se alerta falhar
            
            raise


# Métricas em memória (em produção, usar Prometheus/StatsD)
class Metrics:
    """Coletor de métricas simples em memória"""
    
    def __init__(self):
        self.request_count = 0
        self.error_count = 0
        self.response_times = []
        self.endpoint_counts = {}
        self.stripe_events = {}
        self.account_creations = 0
        self.login_attempts = 0
        self.login_failures = 0
    
    def record_request(self, path: str, duration_ms: float, status_code: int):
        self.request_count += 1
        self.response_times.append(duration_ms)
        
        # Limitar histórico de response times
        if len(self.response_times) > 1000:
            self.response_times = self.response_times[-1000:]
        
        # Contar por endpoint
        self.endpoint_counts[path] = self.endpoint_counts.get(path, 0) + 1
        
        if status_code >= 500:
            self.error_count += 1
    
    def record_stripe_event(self, event_type: str):
        self.stripe_events[event_type] = self.stripe_events.get(event_type, 0) + 1
    
    def record_account_creation(self):
        self.account_creations += 1
    
    def record_login_attempt(self, success: bool):
        self.login_attempts += 1
        if not success:
            self.login_failures += 1
    
    def get_stats(self) -> dict:
        avg_response_time = (
            sum(self.response_times) / len(self.response_times)
            if self.response_times else 0
        )
        
        return {
            "total_requests": self.request_count,
            "total_errors": self.error_count,
            "error_rate": (
                self.error_count / self.request_count * 100
                if self.request_count > 0 else 0
            ),
            "avg_response_time_ms": round(avg_response_time, 2),
            "endpoints": self.endpoint_counts,
            "stripe_events": self.stripe_events,
            "accounts": {
                "created": self.account_creations,
                "login_attempts": self.login_attempts,
                "login_failures": self.login_failures
            }
        }


# Instância global de métricas
metrics = Metrics()
