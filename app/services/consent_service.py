"""
Serviço de gerenciamento de consentimento (LGPD)
Logs de consentimento e auditoria de mensagens
"""
import logging
from datetime import datetime
from typing import Optional
from app.infra.db import get_db_connection

logger = logging.getLogger(__name__)


class ConsentService:
    """
    Gerencia consentimento LGPD e auditoria de mensagens
    """
    
    async def has_consent(self, user_id: str) -> bool:
        """
        Verifica se o usuário deu consentimento
        
        Args:
            user_id: ID do usuário
            
        Returns:
            True se tem consentimento ativo
        """
        try:
            db = await get_db_connection()
            
            query = """
                SELECT consent_given, consent_date
                FROM user_consents
                WHERE user_id = $1
                AND consent_given = true
                AND revoked_at IS NULL
                ORDER BY consent_date DESC
                LIMIT 1
            """
            
            result = await db.fetchrow(query, user_id)
            return result is not None
            
        except Exception as e:
            logger.error(f"Erro ao verificar consentimento: {str(e)}", exc_info=True)
            return False
    
    async def register_consent(self, user_id: str, ip_address: Optional[str] = None) -> bool:
        """
        Registra consentimento do usuário
        
        Args:
            user_id: ID do usuário
            ip_address: Endereço IP (opcional)
            
        Returns:
            True se registrado com sucesso
        """
        try:
            db = await get_db_connection()
            
            query = """
                INSERT INTO user_consents (user_id, consent_given, consent_date, ip_address)
                VALUES ($1, true, $2, $3)
                ON CONFLICT (user_id) 
                DO UPDATE SET 
                    consent_given = true,
                    consent_date = $2,
                    revoked_at = NULL
            """
            
            await db.execute(query, user_id, datetime.now(), ip_address)
            logger.info(f"Consentimento registrado para usuário {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao registrar consentimento: {str(e)}", exc_info=True)
            return False
    
    async def revoke_consent(self, user_id: str) -> bool:
        """
        Revoga consentimento do usuário
        
        Args:
            user_id: ID do usuário
            
        Returns:
            True se revogado com sucesso
        """
        try:
            db = await get_db_connection()
            
            query = """
                UPDATE user_consents
                SET revoked_at = $1
                WHERE user_id = $2
                AND revoked_at IS NULL
            """
            
            await db.execute(query, datetime.now(), user_id)
            logger.info(f"Consentimento revogado para usuário {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao revogar consentimento: {str(e)}", exc_info=True)
            return False
    
    async def log_message(
        self,
        user_id: str,
        incoming_message: str,
        outgoing_message: str
    ) -> bool:
        """
        Registra mensagem para auditoria (LGPD)
        
        Args:
            user_id: ID do usuário
            incoming_message: Mensagem recebida
            outgoing_message: Mensagem enviada
            
        Returns:
            True se registrado com sucesso
        """
        try:
            db = await get_db_connection()
            
            query = """
                INSERT INTO message_logs (
                    user_id,
                    incoming_message,
                    outgoing_message,
                    created_at
                )
                VALUES ($1, $2, $3, $4)
            """
            
            await db.execute(
                query,
                user_id,
                incoming_message,
                outgoing_message,
                datetime.now()
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao registrar mensagem: {str(e)}", exc_info=True)
            return False
