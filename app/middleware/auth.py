"""
Sistema de Autenticação API
===========================

Suporta múltiplos métodos de autenticação:
1. API Keys - Para integrações server-to-server
2. JWT Tokens - Para autenticação de usuários/sessões
3. Webhook Signatures - Para validar webhooks externos

Níveis de acesso:
- public: Sem autenticação necessária
- authenticated: Requer API Key ou JWT válido
- admin: Requer API Key com permissão admin
"""
import os
import hmac
import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from functools import wraps

from fastapi import Request, HTTPException, Depends, Security
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from pydantic import BaseModel

from app.infra.redis import get_redis_client
from app.infra.db import get_db_connection

logger = logging.getLogger(__name__)

# Configurações JWT
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

# Configurações API Key
API_KEY_HEADER = "X-API-Key"
API_KEY_PREFIX = "quickvet:apikey:"

# Security schemes
api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


class TokenPayload(BaseModel):
    """Payload do JWT Token"""
    sub: str  # Subject (user_id ou account_id)
    type: str  # Tipo: "user", "account", "service"
    permissions: List[str] = []
    exp: datetime
    iat: datetime


class APIKeyInfo(BaseModel):
    """Informações de uma API Key"""
    key_id: str
    account_id: str
    name: str
    permissions: List[str]
    created_at: datetime
    last_used_at: Optional[datetime] = None
    is_active: bool = True


class AuthenticatedUser(BaseModel):
    """Usuário autenticado (de JWT ou API Key)"""
    id: str
    type: str  # "user", "account", "service", "apikey"
    permissions: List[str] = []
    account_id: Optional[str] = None
    metadata: Dict[str, Any] = {}


# ==================== JWT FUNCTIONS ====================

def create_jwt_token(
    subject: str,
    token_type: str = "user",
    permissions: List[str] = None,
    expiration_hours: int = None
) -> str:
    """
    Cria um JWT token.
    
    Args:
        subject: ID do usuário ou conta
        token_type: Tipo do token
        permissions: Lista de permissões
        expiration_hours: Horas até expiração
        
    Returns:
        Token JWT encodado
    """
    if expiration_hours is None:
        expiration_hours = JWT_EXPIRATION_HOURS
    
    now = datetime.utcnow()
    payload = {
        "sub": subject,
        "type": token_type,
        "permissions": permissions or [],
        "iat": now,
        "exp": now + timedelta(hours=expiration_hours)
    }
    
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt_token(token: str) -> Optional[TokenPayload]:
    """
    Decodifica e valida um JWT token.
    
    Returns:
        TokenPayload ou None se inválido
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return TokenPayload(**payload)
    except JWTError as e:
        logger.warning(f"JWT inválido: {e}")
        return None


# ==================== API KEY FUNCTIONS ====================

async def create_api_key(
    account_id: str,
    name: str,
    permissions: List[str] = None
) -> tuple[str, str]:
    """
    Cria uma nova API Key para uma conta.
    
    Returns:
        (key_id, api_key_secret) - A secret só é retornada uma vez!
    """
    # Gerar key_id e secret
    key_id = f"qv_{secrets.token_hex(8)}"
    secret = secrets.token_hex(32)
    api_key = f"{key_id}_{secret}"
    
    # Hash do secret para armazenamento
    secret_hash = hashlib.sha256(secret.encode()).hexdigest()
    
    # Salvar no banco
    db = await get_db_connection()
    
    await db.execute("""
        INSERT INTO api_keys (key_id, account_id, name, secret_hash, permissions, created_at)
        VALUES ($1, $2, $3, $4, $5, $6)
    """, key_id, account_id, name, secret_hash, permissions or [], datetime.utcnow())
    
    logger.info(f"API Key criada: {key_id} para conta {account_id}")
    
    return key_id, api_key


async def validate_api_key(api_key: str) -> Optional[APIKeyInfo]:
    """
    Valida uma API Key.
    
    Returns:
        APIKeyInfo ou None se inválida
    """
    try:
        # Separar key_id e secret
        parts = api_key.split("_", 2)
        if len(parts) != 3 or parts[0] != "qv":
            return None
        
        key_id = f"{parts[0]}_{parts[1]}"
        secret = parts[2]
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()
        
        # Verificar no Redis cache primeiro
        redis = get_redis_client()
        cache_key = f"{API_KEY_PREFIX}{key_id}"
        cached = await redis.get(cache_key)
        
        if cached:
            import json
            key_data = json.loads(cached)
            if key_data.get("secret_hash") == secret_hash:
                return APIKeyInfo(**key_data)
        
        # Buscar no banco
        db = await get_db_connection()
        row = await db.fetchrow("""
            SELECT key_id, account_id, name, secret_hash, permissions, created_at, last_used_at, is_active
            FROM api_keys
            WHERE key_id = $1 AND is_active = true
        """, key_id)
        
        if not row or row["secret_hash"] != secret_hash:
            return None
        
        # Atualizar last_used_at
        await db.execute("""
            UPDATE api_keys SET last_used_at = $1 WHERE key_id = $2
        """, datetime.utcnow(), key_id)
        
        # Cachear por 5 minutos
        key_info = APIKeyInfo(
            key_id=row["key_id"],
            account_id=row["account_id"],
            name=row["name"],
            permissions=row["permissions"] or [],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            is_active=row["is_active"]
        )
        
        import json
        cache_data = {**key_info.model_dump(), "secret_hash": secret_hash}
        cache_data["created_at"] = cache_data["created_at"].isoformat()
        if cache_data["last_used_at"]:
            cache_data["last_used_at"] = cache_data["last_used_at"].isoformat()
        await redis.setex(cache_key, 300, json.dumps(cache_data, default=str))
        
        return key_info
        
    except Exception as e:
        logger.error(f"Erro ao validar API Key: {e}")
        return None


async def revoke_api_key(key_id: str, account_id: str) -> bool:
    """Revoga uma API Key"""
    try:
        db = await get_db_connection()
        result = await db.execute("""
            UPDATE api_keys SET is_active = false
            WHERE key_id = $1 AND account_id = $2
        """, key_id, account_id)
        
        # Invalidar cache
        redis = get_redis_client()
        await redis.delete(f"{API_KEY_PREFIX}{key_id}")
        
        logger.info(f"API Key revogada: {key_id}")
        return True
        
    except Exception as e:
        logger.error(f"Erro ao revogar API Key: {e}")
        return False


# ==================== AUTHENTICATION DEPENDENCIES ====================

async def get_current_user(
    api_key: Optional[str] = Security(api_key_header),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme)
) -> Optional[AuthenticatedUser]:
    """
    Dependency para obter usuário autenticado.
    Aceita API Key ou Bearer Token.
    
    Returns:
        AuthenticatedUser ou None
    """
    # Tentar API Key primeiro
    if api_key:
        key_info = await validate_api_key(api_key)
        if key_info:
            return AuthenticatedUser(
                id=key_info.key_id,
                type="apikey",
                permissions=key_info.permissions,
                account_id=key_info.account_id,
                metadata={"key_name": key_info.name}
            )
    
    # Tentar Bearer Token
    if bearer:
        token_payload = decode_jwt_token(bearer.credentials)
        if token_payload:
            return AuthenticatedUser(
                id=token_payload.sub,
                type=token_payload.type,
                permissions=token_payload.permissions
            )
    
    return None


async def require_auth(
    user: Optional[AuthenticatedUser] = Depends(get_current_user)
) -> AuthenticatedUser:
    """
    Dependency que REQUER autenticação.
    Lança 401 se não autenticado.
    """
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Autenticação necessária",
            headers={"WWW-Authenticate": "Bearer"}
        )
    return user


async def require_admin(
    user: AuthenticatedUser = Depends(require_auth)
) -> AuthenticatedUser:
    """
    Dependency que requer permissão admin.
    """
    if "admin" not in user.permissions:
        raise HTTPException(
            status_code=403,
            detail="Permissão de administrador necessária"
        )
    return user


def require_permission(permission: str):
    """
    Factory para criar dependency que requer permissão específica.
    
    Usage:
        @router.get("/sensitive")
        async def sensitive(user: AuthenticatedUser = Depends(require_permission("read:sensitive"))):
            ...
    """
    async def permission_checker(
        user: AuthenticatedUser = Depends(require_auth)
    ) -> AuthenticatedUser:
        if permission not in user.permissions and "admin" not in user.permissions:
            raise HTTPException(
                status_code=403,
                detail=f"Permissão '{permission}' necessária"
            )
        return user
    
    return permission_checker


# ==================== WEBHOOK SIGNATURE VALIDATION ====================

def validate_webhook_signature(
    payload: bytes,
    signature: str,
    secret: str,
    algorithm: str = "sha256"
) -> bool:
    """
    Valida assinatura HMAC de webhook.
    
    Args:
        payload: Body da requisição em bytes
        signature: Header de assinatura (ex: "sha256=abc123...")
        secret: Secret compartilhado
        algorithm: Algoritmo (sha256, sha1)
        
    Returns:
        True se válido
    """
    try:
        # Extrair algoritmo e hash da assinatura
        parts = signature.split("=", 1)
        if len(parts) == 2:
            sig_algorithm, sig_hash = parts
        else:
            sig_hash = signature
            sig_algorithm = algorithm
        
        # Calcular hash esperado
        if sig_algorithm == "sha256":
            expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        elif sig_algorithm == "sha1":
            expected = hmac.new(secret.encode(), payload, hashlib.sha1).hexdigest()
        else:
            return False
        
        # Comparação segura contra timing attacks
        return hmac.compare_digest(expected, sig_hash)
        
    except Exception as e:
        logger.error(f"Erro ao validar assinatura: {e}")
        return False


# ==================== DECORATORS ====================

def authenticated(func):
    """Decorator para exigir autenticação em uma rota"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Procurar Request nos argumentos
        request = None
        for arg in args:
            if isinstance(arg, Request):
                request = arg
                break
        for v in kwargs.values():
            if isinstance(v, Request):
                request = v
                break
        
        if not request:
            raise HTTPException(status_code=500, detail="Request não encontrada")
        
        # Verificar autenticação
        api_key = request.headers.get(API_KEY_HEADER)
        auth_header = request.headers.get("Authorization")
        
        user = None
        
        if api_key:
            key_info = await validate_api_key(api_key)
            if key_info:
                user = AuthenticatedUser(
                    id=key_info.key_id,
                    type="apikey",
                    permissions=key_info.permissions,
                    account_id=key_info.account_id
                )
        
        if not user and auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            token_payload = decode_jwt_token(token)
            if token_payload:
                user = AuthenticatedUser(
                    id=token_payload.sub,
                    type=token_payload.type,
                    permissions=token_payload.permissions
                )
        
        if not user:
            raise HTTPException(status_code=401, detail="Autenticação necessária")
        
        # Injetar user nos kwargs
        kwargs["current_user"] = user
        
        return await func(*args, **kwargs)
    
    return wrapper
