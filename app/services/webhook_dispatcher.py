"""
Serviço de Disparo de Webhooks (Outbound)
=========================================

Dispara eventos para sistemas externos (n8n, Zapier, etc).
Usado para automações de negócio como:
- Confirmação de compra
- Aviso de plano vencido
- Mudança de plano
"""
import os
import json
import hmac
import hashlib
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, asdict

import httpx

from app.infra.redis import get_redis_client

logger = logging.getLogger(__name__)


# Configurações
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "quickvet_webhook_secret")
WEBHOOK_TIMEOUT = int(os.getenv("WEBHOOK_TIMEOUT", 10))  # segundos
WEBHOOK_RETRY_COUNT = int(os.getenv("WEBHOOK_RETRY_COUNT", 3))


class WebhookEvent(str, Enum):
    """Tipos de eventos que disparam webhooks"""
    
    # Assinatura/Plano
    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_UPDATED = "subscription.updated"
    SUBSCRIPTION_CANCELLED = "subscription.cancelled"
    SUBSCRIPTION_EXPIRED = "subscription.expired"
    
    # Pagamento
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"
    
    # Conta
    ACCOUNT_CREATED = "account.created"
    ACCOUNT_UPDATED = "account.updated"
    
    # Uso
    QUOTA_EXCEEDED = "quota.exceeded"
    QUOTA_WARNING = "quota.warning"  # 80% do limite
    
    # Conversa
    CONVERSATION_STARTED = "conversation.started"
    EMERGENCY_DETECTED = "emergency.detected"


@dataclass
class WebhookPayload:
    """Payload enviado para o webhook"""
    event: str
    timestamp: str
    data: Dict[str, Any]
    account_id: Optional[str] = None
    user_id: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "event": self.event,
            "timestamp": self.timestamp,
            "data": self.data,
            "account_id": self.account_id,
            "user_id": self.user_id
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class WebhookDispatcher:
    """
    Dispara webhooks para sistemas externos.
    
    Features:
    - Assinatura HMAC para validação
    - Retry automático em caso de falha
    - Fila de retry no Redis
    - Logging de todos os disparos
    """
    
    def __init__(self):
        self.base_url = N8N_WEBHOOK_URL
        self.secret = WEBHOOK_SECRET
        self.timeout = WEBHOOK_TIMEOUT
        self.max_retries = WEBHOOK_RETRY_COUNT
    
    def _generate_signature(self, payload: str) -> str:
        """Gera assinatura HMAC-SHA256 do payload"""
        return hmac.new(
            self.secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
    
    async def dispatch(
        self,
        event: WebhookEvent,
        data: Dict[str, Any],
        account_id: Optional[str] = None,
        user_id: Optional[str] = None,
        custom_url: Optional[str] = None
    ) -> bool:
        """
        Dispara um webhook para o n8n.
        
        Args:
            event: Tipo do evento
            data: Dados do evento
            account_id: ID da conta (clínica)
            user_id: ID do usuário (WhatsApp)
            custom_url: URL customizada (sobrescreve N8N_WEBHOOK_URL)
            
        Returns:
            True se enviado com sucesso
        """
        url = custom_url or self.base_url
        
        if not url:
            logger.warning(f"Webhook não configurado, evento {event.value} ignorado")
            return False
        
        # Criar payload
        payload = WebhookPayload(
            event=event.value,
            timestamp=datetime.utcnow().isoformat() + "Z",
            data=data,
            account_id=account_id,
            user_id=user_id
        )
        
        payload_json = payload.to_json()
        signature = self._generate_signature(payload_json)
        
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Webhook-Event": event.value,
            "X-Webhook-Timestamp": payload.timestamp
        }
        
        # Tentar enviar com retry
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        url,
                        content=payload_json,
                        headers=headers
                    )
                    
                    if response.status_code in [200, 201, 202, 204]:
                        logger.info(
                            f"Webhook enviado: {event.value} → {url} "
                            f"(status: {response.status_code})"
                        )
                        return True
                    else:
                        logger.warning(
                            f"Webhook falhou: {event.value} → {url} "
                            f"(status: {response.status_code}, tentativa {attempt + 1})"
                        )
                        
            except Exception as e:
                logger.error(
                    f"Erro ao enviar webhook: {event.value} → {url} "
                    f"(erro: {e}, tentativa {attempt + 1})"
                )
        
        # Todas as tentativas falharam - salvar para retry posterior
        await self._save_failed_webhook(payload, url)
        return False
    
    async def _save_failed_webhook(self, payload: WebhookPayload, url: str):
        """Salva webhook falho no Redis para retry posterior"""
        try:
            redis = get_redis_client()
            failed_data = {
                "payload": payload.to_dict(),
                "url": url,
                "failed_at": datetime.utcnow().isoformat()
            }
            await redis.lpush(
                "quickvet:webhooks:failed",
                json.dumps(failed_data)
            )
            logger.info(f"Webhook falho salvo para retry: {payload.event}")
        except Exception as e:
            logger.error(f"Erro ao salvar webhook falho: {e}")
    
    async def retry_failed_webhooks(self, max_items: int = 10) -> int:
        """
        Tenta reenviar webhooks que falharam.
        Pode ser chamado periodicamente por um job.
        
        Returns:
            Número de webhooks reenviados com sucesso
        """
        try:
            redis = get_redis_client()
            success_count = 0
            
            for _ in range(max_items):
                # Pegar próximo webhook falho
                raw = await redis.rpop("quickvet:webhooks:failed")
                if not raw:
                    break
                
                failed_data = json.loads(raw)
                payload_dict = failed_data["payload"]
                url = failed_data["url"]
                
                # Recriar payload
                payload = WebhookPayload(**payload_dict)
                
                # Tentar enviar novamente
                success = await self.dispatch(
                    event=WebhookEvent(payload.event),
                    data=payload.data,
                    account_id=payload.account_id,
                    user_id=payload.user_id,
                    custom_url=url
                )
                
                if success:
                    success_count += 1
            
            return success_count
            
        except Exception as e:
            logger.error(f"Erro ao reenviar webhooks: {e}")
            return 0
    
    # ==================== MÉTODOS DE CONVENIÊNCIA ====================
    
    async def notify_subscription_created(
        self,
        account_id: str,
        plan_type: str,
        stripe_subscription_id: str,
        email: str
    ):
        """Notifica criação de nova assinatura"""
        await self.dispatch(
            event=WebhookEvent.SUBSCRIPTION_CREATED,
            data={
                "plan_type": plan_type,
                "stripe_subscription_id": stripe_subscription_id,
                "email": email
            },
            account_id=account_id
        )
    
    async def notify_subscription_updated(
        self,
        account_id: str,
        old_plan: str,
        new_plan: str
    ):
        """Notifica atualização de assinatura (mudança de plano)"""
        await self.dispatch(
            event=WebhookEvent.SUBSCRIPTION_UPDATED,
            data={
                "old_plan": old_plan,
                "new_plan": new_plan
            },
            account_id=account_id
        )
    
    async def notify_subscription_cancelled(
        self,
        account_id: str,
        plan_type: str,
        reason: Optional[str] = None
    ):
        """Notifica cancelamento de assinatura"""
        await self.dispatch(
            event=WebhookEvent.SUBSCRIPTION_CANCELLED,
            data={
                "plan_type": plan_type,
                "reason": reason
            },
            account_id=account_id
        )
    
    async def notify_subscription_expired(
        self,
        account_id: str,
        plan_type: str,
        expired_at: str
    ):
        """Notifica expiração de plano"""
        await self.dispatch(
            event=WebhookEvent.SUBSCRIPTION_EXPIRED,
            data={
                "plan_type": plan_type,
                "expired_at": expired_at
            },
            account_id=account_id
        )
    
    async def notify_payment_succeeded(
        self,
        account_id: str,
        amount: int,
        currency: str,
        invoice_url: Optional[str] = None
    ):
        """Notifica pagamento confirmado"""
        await self.dispatch(
            event=WebhookEvent.PAYMENT_SUCCEEDED,
            data={
                "amount": amount,
                "currency": currency,
                "amount_formatted": f"R$ {amount / 100:.2f}",
                "invoice_url": invoice_url
            },
            account_id=account_id
        )
    
    async def notify_payment_failed(
        self,
        account_id: str,
        amount: int,
        currency: str,
        error_message: Optional[str] = None
    ):
        """Notifica falha no pagamento"""
        await self.dispatch(
            event=WebhookEvent.PAYMENT_FAILED,
            data={
                "amount": amount,
                "currency": currency,
                "amount_formatted": f"R$ {amount / 100:.2f}",
                "error_message": error_message
            },
            account_id=account_id
        )
    
    async def notify_account_created(
        self,
        account_id: str,
        email: str,
        clinic_name: Optional[str] = None
    ):
        """Notifica criação de nova conta"""
        await self.dispatch(
            event=WebhookEvent.ACCOUNT_CREATED,
            data={
                "email": email,
                "clinic_name": clinic_name
            },
            account_id=account_id
        )
    
    async def notify_quota_exceeded(
        self,
        user_id: str,
        daily_limit: int,
        account_id: Optional[str] = None
    ):
        """Notifica que usuário excedeu quota diária"""
        await self.dispatch(
            event=WebhookEvent.QUOTA_EXCEEDED,
            data={
                "daily_limit": daily_limit
            },
            account_id=account_id,
            user_id=user_id
        )
    
    async def notify_emergency_detected(
        self,
        user_id: str,
        message: str,
        detected_keywords: List[str],
        account_id: Optional[str] = None
    ):
        """Notifica detecção de possível emergência"""
        await self.dispatch(
            event=WebhookEvent.EMERGENCY_DETECTED,
            data={
                "message": message,
                "detected_keywords": detected_keywords
            },
            account_id=account_id,
            user_id=user_id
        )


# Instância global
webhook_dispatcher = WebhookDispatcher()
