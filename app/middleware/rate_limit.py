"""
Rate Limiting Middleware com Limites por Plano
==============================================

Sistema de rate limiting dinâmico similar à OpenAI:
- Limites diferentes por plano (gratuito, mensal, trimestral, semestral, anual)
- Planos mais longos = limites mais generosos
- Burst allowance para picos de uso
- Sliding Window para contagem precisa
"""
import time
import logging
from typing import Optional, Callable, Dict, List
from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_429_TOO_MANY_REQUESTS
import os

from app.infra.redis import get_redis_client

logger = logging.getLogger(__name__)


# ==================== CONFIGURAÇÃO DE LIMITES POR PLANO ====================

class PlanTier:
    """Tiers de plano com seus limites"""
    
    # Estrutura: {requests_per_minute, requests_per_day, tokens_per_minute, burst_allowance}
    TIERS = {
        # Plano gratuito - limites básicos
        "free": {
            "rpm": 10,           # Requests por minuto
            "rpd": 100,          # Requests por dia
            "tpm": 5000,         # Tokens por minuto (para RAG)
            "burst": 5,          # Burst allowance (requests extras permitidos)
            "concurrent": 2,     # Requests simultâneas
            "priority": 1,       # Prioridade na fila (1 = baixa)
        },
        
        # Plano mensal - limites intermediários
        "monthly": {
            "rpm": 30,
            "rpd": 500,
            "tpm": 20000,
            "burst": 15,
            "concurrent": 5,
            "priority": 2,
        },
        
        # Plano trimestral - limites bons
        "quarterly": {
            "rpm": 60,
            "rpd": 1500,
            "tpm": 50000,
            "burst": 30,
            "concurrent": 10,
            "priority": 3,
        },
        
        # Plano semestral - limites generosos
        "semiannual": {
            "rpm": 100,
            "rpd": 3000,
            "tpm": 100000,
            "burst": 50,
            "concurrent": 15,
            "priority": 4,
        },
        
        # Plano anual - limites premium
        "annual": {
            "rpm": 200,
            "rpd": 10000,
            "tpm": 200000,
            "burst": 100,
            "concurrent": 25,
            "priority": 5,
        },
        
        # Enterprise - sem limites práticos
        "enterprise": {
            "rpm": 1000,
            "rpd": 100000,
            "tpm": 1000000,
            "burst": 500,
            "concurrent": 100,
            "priority": 10,
        },
    }
    
    # Mapeamento de nomes alternativos para tiers
    PLAN_MAPPING = {
        "free": "free",
        "gratuito": "free",
        "trial": "free",
        "monthly": "monthly",
        "mensal": "monthly",
        "quarterly": "quarterly",
        "trimestral": "quarterly",
        "semiannual": "semiannual",
        "semestral": "semiannual",
        "annual": "annual",
        "anual": "annual",
        "yearly": "annual",
        "enterprise": "enterprise",
        "unlimited": "enterprise",
    }
    
    @classmethod
    def get_tier(cls, plan_type: str) -> Dict:
        """Obtém configuração do tier pelo tipo de plano"""
        normalized = cls.PLAN_MAPPING.get(plan_type.lower(), "free")
        return cls.TIERS.get(normalized, cls.TIERS["free"])
    
    @classmethod
    def get_tier_name(cls, plan_type: str) -> str:
        """Obtém nome normalizado do tier"""
        return cls.PLAN_MAPPING.get(plan_type.lower(), "free")


# Multiplicadores por endpoint (alguns endpoints são mais "pesados")
ENDPOINT_WEIGHTS = {
    "/api/webhook/whatsapp": 1.0,        # Normal
    "/api/knowledge/search": 2.0,         # Pesado (usa embedding)
    "/api/structural/navigate": 3.0,      # Muito pesado (usa LLM para navegar)
    "/api/knowledge/ingest": 5.0,         # Muito pesado (processa PDFs)
    "/api/structural/ingest": 5.0,
    "default": 1.0,
}

# Prefixo Redis
RATE_LIMIT_PREFIX = "quickvet:ratelimit:"

# Configurações gerais
WHITELIST_IPS = os.getenv("RATE_LIMIT_WHITELIST", "127.0.0.1").split(",")
BLACKLIST_IPS = [ip for ip in os.getenv("RATE_LIMIT_BLACKLIST", "").split(",") if ip]


class RateLimitExceeded(HTTPException):
    """Exceção para rate limit excedido"""
    def __init__(self, limit_type: str, retry_after: int = 60, tier: str = "free"):
        detail = {
            "error": "rate_limit_exceeded",
            "message": f"Limite de {limit_type} excedido para seu plano ({tier})",
            "limit_type": limit_type,
            "tier": tier,
            "retry_after_seconds": retry_after,
            "upgrade_url": "/api/stripe/upgrade"  # URL para upgrade
        }
        super().__init__(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Tier": tier
            }
        )


class DynamicRateLimiter:
    """
    Rate Limiter dinâmico baseado no plano do usuário.
    
    Features:
    - Limites por minuto (RPM) e por dia (RPD)
    - Burst allowance para picos
    - Diferentes limites por endpoint
    - Cache do plano do usuário
    """
    
    def __init__(self):
        self.redis = None
        self.plan_cache_ttl = 300  # Cache do plano por 5 minutos
    
    async def _get_redis(self):
        if self.redis is None:
            self.redis = get_redis_client()
        return self.redis
    
    async def get_user_plan(self, identifier: str) -> str:
        """
        Obtém o plano do usuário.
        
        Args:
            identifier: user_id, account_id ou phone_number
            
        Returns:
            Tipo do plano (free, monthly, quarterly, etc)
        """
        redis = await self._get_redis()
        
        # Verificar cache primeiro
        cache_key = f"{RATE_LIMIT_PREFIX}plan:{identifier}"
        cached_plan = await redis.get(cache_key)
        
        if cached_plan:
            return cached_plan
        
        # Buscar no banco
        try:
            from app.infra.db import get_db_connection
            db = await get_db_connection()
            
            # Tentar encontrar por diferentes identificadores
            plan_type = None
            
            # Buscar por user_id/phone
            result = await db.fetchrow("""
                SELECT p.plan_type, p.status
                FROM plans p
                JOIN users u ON p.user_id = u.user_id
                WHERE u.user_id = $1 OR u.phone_number = $1
                AND p.status = 'active'
                ORDER BY p.created_at DESC
                LIMIT 1
            """, identifier)
            
            if result and result["status"] == "active":
                plan_type = result["plan_type"]
            
            # Se não encontrou, tentar por account_id
            if not plan_type:
                result = await db.fetchrow("""
                    SELECT plan_type, plan_status
                    FROM accounts
                    WHERE account_id = $1 AND plan_status = 'active'
                """, identifier)
                
                if result:
                    plan_type = result["plan_type"]
            
            # Default para free
            plan_type = plan_type or "free"
            
            # Cachear resultado
            await redis.setex(cache_key, self.plan_cache_ttl, plan_type)
            
            return plan_type
            
        except Exception as e:
            logger.warning(f"Erro ao buscar plano do usuário {identifier}: {e}")
            return "free"
    
    async def check_rate_limit(
        self,
        identifier: str,
        endpoint: str = "default",
        plan_type: Optional[str] = None
    ) -> Dict:
        """
        Verifica rate limits para o identificador.
        
        Returns:
            {
                "allowed": bool,
                "tier": str,
                "limits": {rpm, rpd, remaining_rpm, remaining_rpd},
                "retry_after": int (se não permitido)
            }
        """
        try:
            redis = await self._get_redis()
            
            # Obter plano se não fornecido
            if plan_type is None:
                plan_type = await self.get_user_plan(identifier)
            
            tier_name = PlanTier.get_tier_name(plan_type)
            tier_config = PlanTier.get_tier(plan_type)
            
            # Peso do endpoint
            weight = ENDPOINT_WEIGHTS.get(endpoint, ENDPOINT_WEIGHTS["default"])
            
            now = time.time()
            minute_window = int(now / 60)
            day_window = int(now / 86400)
            
            # Chaves Redis
            rpm_key = f"{RATE_LIMIT_PREFIX}rpm:{identifier}:{minute_window}"
            rpd_key = f"{RATE_LIMIT_PREFIX}rpd:{identifier}:{day_window}"
            
            # Obter contadores atuais
            pipe = redis.pipeline()
            pipe.get(rpm_key)
            pipe.get(rpd_key)
            results = await pipe.execute()
            
            current_rpm = int(results[0] or 0)
            current_rpd = int(results[1] or 0)
            
            # Calcular limites efetivos (considerando peso e burst)
            effective_rpm = tier_config["rpm"] + tier_config["burst"]
            effective_rpd = tier_config["rpd"]
            
            # Verificar RPM
            weighted_increment = int(weight)
            
            if current_rpm + weighted_increment > effective_rpm:
                # Calcular retry_after
                seconds_until_next_minute = 60 - (now % 60)
                
                return {
                    "allowed": False,
                    "tier": tier_name,
                    "limit_type": "rpm",
                    "limits": {
                        "rpm": tier_config["rpm"],
                        "rpd": tier_config["rpd"],
                        "current_rpm": current_rpm,
                        "current_rpd": current_rpd,
                        "remaining_rpm": 0,
                        "remaining_rpd": max(0, effective_rpd - current_rpd),
                    },
                    "retry_after": int(seconds_until_next_minute) + 1
                }
            
            # Verificar RPD
            if current_rpd + weighted_increment > effective_rpd:
                # Calcular retry_after até meia-noite
                seconds_until_midnight = 86400 - (now % 86400)
                
                return {
                    "allowed": False,
                    "tier": tier_name,
                    "limit_type": "rpd",
                    "limits": {
                        "rpm": tier_config["rpm"],
                        "rpd": tier_config["rpd"],
                        "current_rpm": current_rpm,
                        "current_rpd": current_rpd,
                        "remaining_rpm": max(0, effective_rpm - current_rpm),
                        "remaining_rpd": 0,
                    },
                    "retry_after": int(seconds_until_midnight) + 1
                }
            
            # Incrementar contadores
            pipe = redis.pipeline()
            pipe.incrby(rpm_key, weighted_increment)
            pipe.expire(rpm_key, 120)  # 2 minutos de TTL
            pipe.incrby(rpd_key, weighted_increment)
            pipe.expire(rpd_key, 90000)  # ~25 horas de TTL
            await pipe.execute()
            
            return {
                "allowed": True,
                "tier": tier_name,
                "limits": {
                    "rpm": tier_config["rpm"],
                    "rpd": tier_config["rpd"],
                    "current_rpm": current_rpm + weighted_increment,
                    "current_rpd": current_rpd + weighted_increment,
                    "remaining_rpm": effective_rpm - current_rpm - weighted_increment,
                    "remaining_rpd": effective_rpd - current_rpd - weighted_increment,
                },
                "retry_after": 0
            }
            
        except Exception as e:
            logger.error(f"Erro no rate limiter: {e}")
            # Fail open - permitir em caso de erro
            return {
                "allowed": True,
                "tier": "unknown",
                "limits": {},
                "retry_after": 0
            }
    
    async def get_usage_stats(self, identifier: str) -> Dict:
        """Retorna estatísticas de uso do rate limit"""
        plan_type = await self.get_user_plan(identifier)
        tier_name = PlanTier.get_tier_name(plan_type)
        tier_config = PlanTier.get_tier(plan_type)
        
        redis = await self._get_redis()
        now = time.time()
        minute_window = int(now / 60)
        day_window = int(now / 86400)
        
        rpm_key = f"{RATE_LIMIT_PREFIX}rpm:{identifier}:{minute_window}"
        rpd_key = f"{RATE_LIMIT_PREFIX}rpd:{identifier}:{day_window}"
        
        current_rpm = int(await redis.get(rpm_key) or 0)
        current_rpd = int(await redis.get(rpd_key) or 0)
        
        return {
            "identifier": identifier,
            "tier": tier_name,
            "plan_type": plan_type,
            "limits": {
                "rpm": tier_config["rpm"],
                "rpd": tier_config["rpd"],
                "burst": tier_config["burst"],
                "concurrent": tier_config["concurrent"],
            },
            "usage": {
                "rpm": current_rpm,
                "rpd": current_rpd,
            },
            "remaining": {
                "rpm": max(0, tier_config["rpm"] + tier_config["burst"] - current_rpm),
                "rpd": max(0, tier_config["rpd"] - current_rpd),
            },
            "reset": {
                "rpm_resets_in_seconds": 60 - int(now % 60),
                "rpd_resets_in_seconds": 86400 - int(now % 86400),
            }
        }
    
    async def invalidate_plan_cache(self, identifier: str):
        """Invalida cache do plano (chamar quando plano mudar)"""
        redis = await self._get_redis()
        cache_key = f"{RATE_LIMIT_PREFIX}plan:{identifier}"
        await redis.delete(cache_key)
        logger.info(f"Cache de plano invalidado para {identifier}")


# Instância global
rate_limiter = DynamicRateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware de Rate Limiting dinâmico por plano.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Obter identificador (IP ou user_id se autenticado)
        identifier = self._get_identifier(request)
        path = request.url.path
        
        # Verificar whitelist
        client_ip = self._get_client_ip(request)
        if client_ip in WHITELIST_IPS:
            return await call_next(request)
        
        # Verificar blacklist
        if client_ip in BLACKLIST_IPS:
            raise HTTPException(status_code=403, detail="IP bloqueado")
        
        # Ignorar endpoints que não precisam de rate limit
        if self._should_skip(path):
            return await call_next(request)
        
        # Verificar rate limit
        result = await rate_limiter.check_rate_limit(
            identifier=identifier,
            endpoint=path
        )
        
        if not result["allowed"]:
            # Disparar alerta de abuso se excedido múltiplas vezes
            try:
                redis = await rate_limiter._get_redis()
                abuse_key = f"{RATE_LIMIT_PREFIX}abuse:{client_ip}:{path}"
                attempts = await redis.incr(abuse_key)
                await redis.expire(abuse_key, 3600)  # 1 hora
                
                if attempts >= 5:  # 5 tentativas em 1 hora
                    from app.services.alert_service import alert_service
                    await alert_service.alert_rate_limit_abuse(
                        ip=client_ip,
                        endpoint=path,
                        attempts=attempts
                    )
            except:
                pass  # Não bloquear se alerta falhar
            
            raise RateLimitExceeded(
                limit_type=result.get("limit_type", "rpm"),
                retry_after=result["retry_after"],
                tier=result["tier"]
            )
        
        # Processar request
        response = await call_next(request)
        
        # Adicionar headers de rate limit
        limits = result.get("limits", {})
        response.headers["X-RateLimit-Tier"] = result["tier"]
        response.headers["X-RateLimit-Limit-RPM"] = str(limits.get("rpm", 0))
        response.headers["X-RateLimit-Limit-RPD"] = str(limits.get("rpd", 0))
        response.headers["X-RateLimit-Remaining-RPM"] = str(limits.get("remaining_rpm", 0))
        response.headers["X-RateLimit-Remaining-RPD"] = str(limits.get("remaining_rpd", 0))
        
        return response
    
    def _get_identifier(self, request: Request) -> str:
        """Obtém identificador do usuário"""
        # Tentar obter user_id do header de autenticação
        api_key = request.headers.get("X-API-Key")
        if api_key and api_key.startswith("qv_"):
            # Extrair key_id da API Key
            parts = api_key.split("_")
            if len(parts) >= 2:
                return f"apikey_{parts[1]}"
        
        # Tentar obter do JWT
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            try:
                from app.middleware.auth import decode_jwt_token
                token = auth_header.split(" ")[1]
                payload = decode_jwt_token(token)
                if payload:
                    return f"user_{payload.sub}"
            except:
                pass
        
        # Para webhook WhatsApp, usar phone number
        if "/webhook/whatsapp" in request.url.path:
            # O phone será extraído do body, mas por enquanto usar IP
            pass
        
        # Fallback para IP
        return f"ip_{self._get_client_ip(request)}"
    
    def _get_client_ip(self, request: Request) -> str:
        """Obtém IP real do cliente"""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"
    
    def _should_skip(self, path: str) -> bool:
        """Verifica se deve pular rate limiting para o path"""
        skip_paths = [
            "/health",
            "/metrics", 
            "/",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/favicon.ico",
        ]
        # Pular rate limit para endpoints de admin e ingestão de conhecimento
        if path.startswith("/api/admin") or path.startswith("/api/knowledge/ingest") or path.startswith("/api/structural/ingest"):
            return True
        return path in skip_paths or path.startswith("/static")


# ==================== HELPERS ====================

async def get_plan_limits(plan_type: str) -> Dict:
    """Retorna limites para um tipo de plano"""
    tier_name = PlanTier.get_tier_name(plan_type)
    tier_config = PlanTier.get_tier(plan_type)
    
    return {
        "tier": tier_name,
        "limits": tier_config,
        "all_tiers": {
            name: config for name, config in PlanTier.TIERS.items()
        }
    }


async def on_plan_change(identifier: str, new_plan: str):
    """
    Callback para quando um plano muda.
    Deve ser chamado pelo webhook do Stripe ou serviço de planos.
    """
    await rate_limiter.invalidate_plan_cache(identifier)
    logger.info(f"Plano alterado para {identifier}: {new_plan}")
