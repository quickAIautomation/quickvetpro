"""
Serviço de Autenticação OAuth2
==============================

Suporta Google e Apple Sign In para criação de contas.
"""
import os
import logging
import httpx
from typing import Optional, Dict, Any
from jose import jwt
import json

from app.infra.db import get_db_connection
from app.middleware.auth import create_jwt_token

logger = logging.getLogger(__name__)

# Configurações OAuth
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
APPLE_CLIENT_ID = os.getenv("APPLE_CLIENT_ID", "")
APPLE_TEAM_ID = os.getenv("APPLE_TEAM_ID", "")
APPLE_KEY_ID = os.getenv("APPLE_KEY_ID", "")


class OAuthService:
    """Serviço para autenticação OAuth2"""
    
    async def verify_google_token(self, id_token: str) -> Optional[Dict[str, Any]]:
        """
        Verifica token do Google OAuth
        
        Args:
            id_token: Token ID do Google
            
        Returns:
            Dados do usuário ou None se inválido
        """
        try:
            # Buscar certificados públicos do Google
            async with httpx.AsyncClient() as client:
                certs_response = await client.get(
                    "https://www.googleapis.com/oauth2/v3/certs"
                )
                certs = certs_response.json()
            
            # Decodificar token (simplificado - em produção usar biblioteca adequada)
            # Por enquanto, vamos validar via API do Google
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
                )
                
                if response.status_code != 200:
                    logger.warning("Token Google inválido")
                    return None
                
                token_data = response.json()
                
                # Verificar se o token é para nosso cliente
                if token_data.get("aud") != GOOGLE_CLIENT_ID:
                    logger.warning("Token Google para cliente diferente")
                    return None
                
                return {
                    "email": token_data.get("email"),
                    "name": token_data.get("name"),
                    "picture": token_data.get("picture"),
                    "sub": token_data.get("sub"),  # Google user ID
                    "provider": "google"
                }
                
        except Exception as e:
            logger.error(f"Erro ao verificar token Google: {e}", exc_info=True)
            return None
    
    async def verify_apple_token(self, id_token: str) -> Optional[Dict[str, Any]]:
        """
        Verifica token do Apple Sign In
        
        Args:
            id_token: Token ID do Apple
            
        Returns:
            Dados do usuário ou None se inválido
        """
        try:
            # Decodificar token JWT do Apple (sem verificar assinatura por enquanto)
            # Em produção, verificar assinatura com chaves públicas da Apple
            try:
                # Decodificar sem verificar (apenas para obter dados)
                decoded = jwt.decode(
                    id_token,
                    options={"verify_signature": False}
                )
                
                return {
                    "email": decoded.get("email"),
                    "name": decoded.get("name") or decoded.get("sub"),
                    "sub": decoded.get("sub"),  # Apple user ID
                    "provider": "apple"
                }
            except Exception:
                logger.warning("Token Apple inválido")
                return None
                
        except Exception as e:
            logger.error(f"Erro ao verificar token Apple: {e}", exc_info=True)
            return None
    
    async def create_or_get_account_from_oauth(
        self,
        email: str,
        name: str,
        provider: str,
        provider_user_id: str
    ) -> Dict[str, Any]:
        """
        Cria ou obtém conta a partir de autenticação OAuth
        
        Args:
            email: Email do usuário
            name: Nome do usuário
            provider: 'google' ou 'apple'
            provider_user_id: ID do usuário no provedor
            
        Returns:
            Dados da conta criada/obtida
        """
        try:
            db = await get_db_connection()
            email_normalized = email.lower().strip()
            
            # Verificar se conta já existe
            account = await db.fetchrow(
                "SELECT * FROM accounts WHERE email = $1",
                email_normalized
            )
            
            if account:
                # Conta existe, retornar
                return {
                    "account_id": account["account_id"],
                    "email": account["email"],
                    "plan_type": account["plan_type"],
                    "plan_status": account["plan_status"],
                    "is_new": False
                }
            
            # Criar nova conta
            import uuid
            from datetime import datetime
            
            account_id = str(uuid.uuid4())
            now = datetime.utcnow()
            
            await db.execute("""
                INSERT INTO accounts (
                    account_id, email, plan_type, plan_status, created_at
                )
                VALUES ($1, $2, 'free', 'pending', $3)
            """, account_id, email_normalized, now)
            
            # Salvar informação de OAuth (opcional, em tabela separada se necessário)
            logger.info(f"Conta criada via OAuth ({provider}): {email_normalized}")
            
            return {
                "account_id": account_id,
                "email": email_normalized,
                "plan_type": "free",
                "plan_status": "pending",
                "is_new": True
            }
            
        except Exception as e:
            logger.error(f"Erro ao criar conta OAuth: {e}", exc_info=True)
            raise


# Instância global
oauth_service = OAuthService()
