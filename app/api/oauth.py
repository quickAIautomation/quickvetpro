"""
API de Autenticação OAuth2
==========================

Endpoints para Google e Apple Sign In.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import logging

from app.services.oauth_service import oauth_service
from app.middleware.auth import create_jwt_token

router = APIRouter(prefix="/auth", tags=["oauth"])
logger = logging.getLogger(__name__)


class GoogleAuthRequest(BaseModel):
    id_token: str


class AppleAuthRequest(BaseModel):
    id_token: str
    user: Optional[dict] = None  # Dados do usuário (Apple pode não enviar email no token)


@router.post("/google")
async def google_auth(request: GoogleAuthRequest):
    """
    Autenticação via Google OAuth
    
    Args:
        request: Contém id_token do Google
        
    Returns:
        Token JWT e dados da conta
    """
    try:
        # Verificar token do Google
        user_data = await oauth_service.verify_google_token(request.id_token)
        
        if not user_data:
            raise HTTPException(status_code=401, detail="Token Google inválido")
        
        # Criar ou obter conta
        account = await oauth_service.create_or_get_account_from_oauth(
            email=user_data["email"],
            name=user_data.get("name", ""),
            provider="google",
            provider_user_id=user_data["sub"]
        )
        
        # Gerar token JWT
        token = create_jwt_token(
            subject=account["account_id"],
            token_type="account",
            permissions=[]
        )
        
        return JSONResponse({
            "token": token,
            "account": {
                "account_id": account["account_id"],
                "email": user_data["email"],
                "name": user_data.get("name"),
                "plan_type": account["plan_type"],
                "plan_status": account["plan_status"],
                "is_new": account["is_new"]
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro na autenticação Google: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao processar autenticação")


@router.post("/apple")
async def apple_auth(request: AppleAuthRequest):
    """
    Autenticação via Apple Sign In
    
    Args:
        request: Contém id_token do Apple
        
    Returns:
        Token JWT e dados da conta
    """
    try:
        # Verificar token do Apple
        user_data = await oauth_service.verify_apple_token(request.id_token)
        
        if not user_data:
            raise HTTPException(status_code=401, detail="Token Apple inválido")
        
        # Se Apple não enviou email no token, usar do request.user
        email = user_data.get("email")
        if not email and request.user:
            email = request.user.get("email")
        
        if not email:
            raise HTTPException(status_code=400, detail="Email não fornecido")
        
        # Criar ou obter conta
        account = await oauth_service.create_or_get_account_from_oauth(
            email=email,
            name=user_data.get("name", ""),
            provider="apple",
            provider_user_id=user_data["sub"]
        )
        
        # Gerar token JWT
        token = create_jwt_token(
            subject=account["account_id"],
            token_type="account",
            permissions=[]
        )
        
        return JSONResponse({
            "token": token,
            "account": {
                "account_id": account["account_id"],
                "email": email,
                "name": user_data.get("name"),
                "plan_type": account["plan_type"],
                "plan_status": account["plan_status"],
                "is_new": account["is_new"]
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro na autenticação Apple: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao processar autenticação")
