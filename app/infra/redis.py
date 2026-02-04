"""
Configuração do Redis para controle de mensagens e sessões
"""
import logging
import redis.asyncio as redis
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Cliente Redis global
_redis_client: Optional[redis.Redis] = None


async def init_redis():
    """
    Inicializa cliente Redis
    """
    global _redis_client
    
    try:
        redis_url = settings.redis_url
        
        _redis_client = redis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True
        )
        
        # Testar conexão
        await _redis_client.ping()
        logger.info(f"Cliente Redis inicializado: {redis_url[:50]}...")
        
    except Exception as e:
        logger.error(f"Erro ao inicializar Redis: {str(e)}", exc_info=True)
        raise


async def close_redis():
    """
    Fecha conexão Redis
    """
    global _redis_client
    
    if _redis_client:
        await _redis_client.close()
        logger.info("Cliente Redis fechado")


def get_redis_client() -> redis.Redis:
    """
    Obtém cliente Redis
    
    Returns:
        Cliente Redis
    """
    if _redis_client is None:
        raise RuntimeError("Redis não inicializado. Chame init_redis() primeiro.")
    
    return _redis_client
