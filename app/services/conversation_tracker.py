"""
Serviço de Rastreamento de Conversas
=====================================

Rastreia conversas do WhatsApp para o dashboard admin.
"""
import logging
from datetime import datetime
from typing import Optional

from app.infra.db import get_db_connection

logger = logging.getLogger(__name__)


class ConversationTracker:
    """Rastreia conversas para o dashboard admin"""
    
    async def track_message(
        self,
        user_id: str,
        phone_number: str,
        role: str,
        content: str,
        has_media: bool = False,
        media_type: Optional[str] = None,
        whatsapp_message_id: Optional[str] = None
    ):
        """
        Rastreia uma mensagem e atualiza a conversa
        
        Args:
            user_id: ID do usuário
            phone_number: Número do WhatsApp
            role: 'user' ou 'assistant'
            content: Conteúdo da mensagem
            has_media: Se tem mídia
            media_type: Tipo da mídia
            whatsapp_message_id: ID da mensagem no WhatsApp
        """
        try:
            db = await get_db_connection()
            
            # Buscar ou criar conversa
            conversation = await db.fetchrow("""
                SELECT conversation_id FROM conversations
                WHERE user_id = $1 OR phone_number = $2
                ORDER BY last_message_at DESC
                LIMIT 1
            """, user_id, phone_number)
            
            if conversation:
                conversation_id = conversation["conversation_id"]
                
                # Atualizar conversa
                await db.execute("""
                    UPDATE conversations
                    SET 
                        last_message_at = $1,
                        last_message_from = $2,
                        last_message_preview = LEFT($3, 200),
                        total_messages = total_messages + 1,
                        status = CASE 
                            WHEN status = 'inactive' THEN 'active'
                            ELSE status
                        END
                    WHERE conversation_id = $4
                """, datetime.utcnow(), role, content, conversation_id)
                
            else:
                # Criar nova conversa
                conversation_id = await db.fetchval("""
                    INSERT INTO conversations (
                        user_id, phone_number, status, last_message_from,
                        last_message_preview, total_messages, started_at
                    )
                    VALUES ($1, $2, 'active', $3, LEFT($4, 200), 1, $5)
                    RETURNING conversation_id
                """, user_id, phone_number, role, content, datetime.utcnow())
            
            # Inserir mensagem
            await db.execute("""
                INSERT INTO conversation_messages (
                    conversation_id, user_id, role, content,
                    has_media, media_type, whatsapp_message_id, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """, conversation_id, user_id, role, content,
                has_media, media_type, whatsapp_message_id, datetime.utcnow())
            
            logger.debug(f"Mensagem rastreada: {role} para {phone_number}")
            
        except Exception as e:
            logger.error(f"Erro ao rastrear mensagem: {e}", exc_info=True)
    
    async def mark_conversation_inactive(self, user_id: str, hours_inactive: int = 24):
        """Marca conversas inativas após período sem mensagens"""
        try:
            db = await get_db_connection()
            
            await db.execute("""
                UPDATE conversations
                SET status = 'inactive'
                WHERE (user_id = $1 OR phone_number = $1)
                AND last_message_at < NOW() - INTERVAL '%d hours'
                AND status = 'active'
            """ % hours_inactive, user_id)
            
        except Exception as e:
            logger.error(f"Erro ao marcar conversa como inativa: {e}", exc_info=True)


# Instância global
conversation_tracker = ConversationTracker()
