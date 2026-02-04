"""
Serviço de Memória de Conversa
==============================

Mantém histórico de contexto entre mensagens do mesmo usuário.
Usa Redis para acesso rápido com TTL automático.

Estrutura no Redis:
- conversation:{user_id}:messages → Lista de mensagens
- conversation:{user_id}:metadata → Metadados da conversa
"""
import os
import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, asdict

from app.infra.redis import get_redis_client

logger = logging.getLogger(__name__)


# Configurações
MAX_MESSAGES = int(os.getenv("CONVERSATION_MAX_MESSAGES", 20))  # Últimas N mensagens
MAX_TOKENS_CONTEXT = int(os.getenv("CONVERSATION_MAX_TOKENS", 4000))  # Limite de tokens
CONVERSATION_TTL = int(os.getenv("CONVERSATION_TTL_HOURS", 24)) * 3600  # Expira após X horas de inatividade

# Prefixos Redis
CONV_PREFIX = "quickvet:conversation:"


@dataclass
class Message:
    """Uma mensagem na conversa"""
    role: str  # "user" ou "assistant"
    content: str
    timestamp: str
    has_media: bool = False
    media_type: Optional[str] = None
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(**data)
    
    def to_openai_format(self) -> dict:
        """Converte para formato da API OpenAI"""
        return {"role": self.role, "content": self.content}


@dataclass
class ConversationContext:
    """Contexto completo de uma conversa"""
    user_id: str
    messages: List[Message]
    started_at: str
    last_activity: str
    total_messages: int
    metadata: Dict[str, Any]
    
    def get_messages_for_prompt(self, max_tokens: int = MAX_TOKENS_CONTEXT) -> List[dict]:
        """
        Retorna mensagens formatadas para o prompt, respeitando limite de tokens.
        Prioriza mensagens mais recentes.
        """
        result = []
        estimated_tokens = 0
        
        # Iterar do mais recente para o mais antigo
        for msg in reversed(self.messages):
            # Estimativa simples: ~4 chars por token
            msg_tokens = len(msg.content) // 4
            
            if estimated_tokens + msg_tokens > max_tokens:
                break
            
            result.insert(0, msg.to_openai_format())
            estimated_tokens += msg_tokens
        
        return result


class ConversationMemory:
    """
    Gerencia memória de conversas usando Redis.
    
    Cada conversa é armazenada como uma lista de mensagens com TTL.
    Após período de inatividade, a conversa expira automaticamente.
    """
    
    def _get_messages_key(self, user_id: str) -> str:
        return f"{CONV_PREFIX}{user_id}:messages"
    
    def _get_metadata_key(self, user_id: str) -> str:
        return f"{CONV_PREFIX}{user_id}:metadata"
    
    async def add_message(
        self,
        user_id: str,
        role: str,
        content: str,
        has_media: bool = False,
        media_type: Optional[str] = None
    ) -> None:
        """
        Adiciona uma mensagem ao histórico da conversa.
        
        Args:
            user_id: ID do usuário (número WhatsApp)
            role: "user" ou "assistant"
            content: Conteúdo da mensagem
            has_media: Se a mensagem contém mídia
            media_type: Tipo da mídia (image, audio, video)
        """
        try:
            redis = get_redis_client()
            messages_key = self._get_messages_key(user_id)
            metadata_key = self._get_metadata_key(user_id)
            
            # Criar mensagem
            message = Message(
                role=role,
                content=content,
                timestamp=datetime.now().isoformat(),
                has_media=has_media,
                media_type=media_type
            )
            
            # Adicionar à lista
            await redis.rpush(messages_key, json.dumps(message.to_dict()))
            
            # Manter apenas últimas N mensagens
            await redis.ltrim(messages_key, -MAX_MESSAGES, -1)
            
            # Atualizar metadata
            metadata = await self._get_or_create_metadata(user_id)
            metadata["last_activity"] = datetime.now().isoformat()
            metadata["total_messages"] = metadata.get("total_messages", 0) + 1
            await redis.set(metadata_key, json.dumps(metadata))
            
            # Renovar TTL
            await redis.expire(messages_key, CONVERSATION_TTL)
            await redis.expire(metadata_key, CONVERSATION_TTL)
            
            logger.debug(f"Mensagem adicionada para {user_id}: {role}")
            
        except Exception as e:
            logger.error(f"Erro ao adicionar mensagem: {e}")
    
    async def get_context(self, user_id: str) -> Optional[ConversationContext]:
        """
        Recupera o contexto completo da conversa.
        
        Args:
            user_id: ID do usuário
            
        Returns:
            ConversationContext ou None se não existir
        """
        try:
            redis = get_redis_client()
            messages_key = self._get_messages_key(user_id)
            metadata_key = self._get_metadata_key(user_id)
            
            # Buscar mensagens
            raw_messages = await redis.lrange(messages_key, 0, -1)
            
            if not raw_messages:
                return None
            
            messages = [
                Message.from_dict(json.loads(m))
                for m in raw_messages
            ]
            
            # Buscar metadata
            raw_metadata = await redis.get(metadata_key)
            metadata = json.loads(raw_metadata) if raw_metadata else {}
            
            return ConversationContext(
                user_id=user_id,
                messages=messages,
                started_at=metadata.get("started_at", ""),
                last_activity=metadata.get("last_activity", ""),
                total_messages=metadata.get("total_messages", len(messages)),
                metadata=metadata
            )
            
        except Exception as e:
            logger.error(f"Erro ao recuperar contexto: {e}")
            return None
    
    async def get_history_for_prompt(
        self,
        user_id: str,
        max_tokens: int = MAX_TOKENS_CONTEXT
    ) -> List[dict]:
        """
        Retorna histórico formatado para usar no prompt do OpenAI.
        
        Args:
            user_id: ID do usuário
            max_tokens: Limite de tokens
            
        Returns:
            Lista de mensagens no formato OpenAI
        """
        context = await self.get_context(user_id)
        
        if not context:
            return []
        
        return context.get_messages_for_prompt(max_tokens)
    
    async def clear_conversation(self, user_id: str) -> bool:
        """
        Limpa o histórico de conversa de um usuário.
        
        Args:
            user_id: ID do usuário
            
        Returns:
            True se limpou com sucesso
        """
        try:
            redis = get_redis_client()
            messages_key = self._get_messages_key(user_id)
            metadata_key = self._get_metadata_key(user_id)
            
            await redis.delete(messages_key, metadata_key)
            logger.info(f"Conversa limpa para {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao limpar conversa: {e}")
            return False
    
    async def get_summary(self, user_id: str) -> Optional[str]:
        """
        Retorna um resumo da conversa atual.
        Útil para contexto condensado em conversas longas.
        """
        context = await self.get_context(user_id)
        
        if not context or not context.messages:
            return None
        
        # Resumo simples baseado nas mensagens
        user_messages = [m for m in context.messages if m.role == "user"]
        
        if not user_messages:
            return None
        
        # Tópicos principais (primeira e última mensagem do usuário)
        first_topic = user_messages[0].content[:100]
        last_topic = user_messages[-1].content[:100] if len(user_messages) > 1 else ""
        
        summary = f"Conversa iniciada sobre: {first_topic}"
        if last_topic and last_topic != first_topic:
            summary += f"\nÚltimo assunto: {last_topic}"
        
        return summary
    
    async def _get_or_create_metadata(self, user_id: str) -> dict:
        """Obtém ou cria metadata da conversa"""
        try:
            redis = get_redis_client()
            metadata_key = self._get_metadata_key(user_id)
            
            raw_metadata = await redis.get(metadata_key)
            
            if raw_metadata:
                return json.loads(raw_metadata)
            
            # Criar nova metadata
            return {
                "started_at": datetime.now().isoformat(),
                "last_activity": datetime.now().isoformat(),
                "total_messages": 0
            }
            
        except Exception as e:
            logger.error(f"Erro ao obter metadata: {e}")
            return {}
    
    async def set_context_variable(
        self,
        user_id: str,
        key: str,
        value: Any
    ) -> None:
        """
        Define uma variável de contexto na conversa.
        Útil para armazenar informações extraídas (nome do pet, espécie, etc).
        
        Args:
            user_id: ID do usuário
            key: Nome da variável
            value: Valor (deve ser serializável em JSON)
        """
        try:
            redis = get_redis_client()
            metadata_key = self._get_metadata_key(user_id)
            
            metadata = await self._get_or_create_metadata(user_id)
            
            if "context_vars" not in metadata:
                metadata["context_vars"] = {}
            
            metadata["context_vars"][key] = value
            await redis.set(metadata_key, json.dumps(metadata))
            await redis.expire(metadata_key, CONVERSATION_TTL)
            
        except Exception as e:
            logger.error(f"Erro ao definir variável de contexto: {e}")
    
    async def get_context_variable(
        self,
        user_id: str,
        key: str,
        default: Any = None
    ) -> Any:
        """
        Obtém uma variável de contexto da conversa.
        
        Args:
            user_id: ID do usuário
            key: Nome da variável
            default: Valor padrão se não existir
            
        Returns:
            Valor da variável ou default
        """
        try:
            metadata = await self._get_or_create_metadata(user_id)
            return metadata.get("context_vars", {}).get(key, default)
            
        except Exception as e:
            logger.error(f"Erro ao obter variável de contexto: {e}")
            return default


# Instância global
conversation_memory = ConversationMemory()
