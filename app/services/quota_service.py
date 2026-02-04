"""
Serviço de controle de quota diária de mensagens
Usa Redis para controle de limite diário
"""
import os
import logging
from datetime import datetime
from typing import Optional
from app.infra.redis import get_redis_client

logger = logging.getLogger(__name__)


class QuotaService:
    """
    Gerencia limites diários de mensagens por usuário
    Redis key: quota:{user_id}:{YYYY-MM-DD}
    """
    
    def __init__(self):
        self.default_daily_limit = int(
            os.getenv("DAILY_MESSAGE_LIMIT", "50")
        )
    
    def _get_redis_client(self):
        """Obtém cliente Redis (lazy initialization)"""
        return get_redis_client()
    
    async def check_and_increment_quota(self, user_id: str) -> bool:
        """
        Verifica se o usuário pode enviar mensagem e incrementa a quota
        
        Args:
            user_id: ID do usuário
            
        Returns:
            True se pode enviar, False se excedeu o limite
        """
        try:
            redis_client = self._get_redis_client()
            today = datetime.now().strftime("%Y-%m-%d")
            quota_key = f"quota:{user_id}:{today}"
            
            # Verificar quota atual
            current_quota = await redis_client.get(quota_key)
            current_quota = int(current_quota) if current_quota else 0
            
            # Verificar limite
            if current_quota >= self.default_daily_limit:
                logger.warning(f"Usuário {user_id} excedeu quota diária: {current_quota}/{self.default_daily_limit}")
                return False
            
            # Incrementar quota
            new_quota = await redis_client.incr(quota_key)
            
            # Definir TTL para reset automático no próximo dia (24 horas)
            if new_quota == 1:  # Primeira mensagem do dia
                await redis_client.expire(quota_key, 86400)  # 24 horas
            
            logger.info(f"Quota atualizada para {user_id}: {new_quota}/{self.default_daily_limit}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao verificar quota: {str(e)}", exc_info=True)
            # Em caso de erro, permitir mensagem (fail-open)
            return True
    
    async def get_quota_status(self, user_id: str) -> dict:
        """
        Retorna status da quota do usuário
        
        Args:
            user_id: ID do usuário
            
        Returns:
            Dict com informações da quota
        """
        try:
            redis_client = self._get_redis_client()
            today = datetime.now().strftime("%Y-%m-%d")
            quota_key = f"quota:{user_id}:{today}"
            
            current_quota = await redis_client.get(quota_key)
            current_quota = int(current_quota) if current_quota else 0
            
            return {
                "user_id": user_id,
                "date": today,
                "current_quota": current_quota,
                "daily_limit": self.default_daily_limit,
                "remaining": max(0, self.default_daily_limit - current_quota)
            }
        except Exception as e:
            logger.error(f"Erro ao obter status da quota: {str(e)}", exc_info=True)
            return {
                "user_id": user_id,
                "error": str(e)
            }
