"""
Agente Veterinario com RAG (Retrieval-Augmented Generation)
===========================================================

Usa MCP (Model Context Protocol) para todas as interações de conhecimento.
Garante padronização entre uso interno e externo (Cursor, etc).

Modos de recuperação:
1. VECTOR: Busca por similaridade semântica (embeddings)
2. STRUCTURAL: Navegação hierárquica estilo PageIndex
3. AUTO: Detecta automaticamente o melhor modo
"""
import logging
from typing import Optional
from enum import Enum
import os

from openai import OpenAI

from app.services.mcp_knowledge_client import mcp_client, MCPToolResult
from app.services.conversation_memory import conversation_memory

logger = logging.getLogger(__name__)


class RetrievalMode(str, Enum):
    """Modo de recuperação de conhecimento - espelha MCP"""
    VECTOR = "vector"
    STRUCTURAL = "structural"
    AUTO = "auto"


class VetAgent:
    """
    Agente Veterinario com:
    - MCP Client para queries de conhecimento (padronizado)
    - Memória de conversa
    - Processamento de mídia
    - Guardrails de segurança
    """
    
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.default_retrieval_mode = RetrievalMode(
            os.getenv("RETRIEVAL_MODE", "auto")
        )
    
    def _get_system_prompt(self, context: str = "") -> str:
        """Prompt do sistema com contexto da base de conhecimento"""
        base_prompt = """Voce e um assistente veterinario virtual especializado em educacao e triagem.

REGRAS OBRIGATORIAS:
1. NUNCA faca diagnosticos definitivos
2. NUNCA prescreva medicamentos ou dosagens
3. NUNCA substitua atendimento veterinario presencial
4. SEMPRE recomende consulta presencial em casos de emergencia
5. Use o CONTEXTO TECNICO fornecido para embasar suas respostas

SUAS RESPONSABILIDADES:
- Fornecer informacoes educativas sobre saude animal
- Fazer triagem basica para orientar sobre urgencia
- Recomendar quando buscar atendimento veterinario
- Explicar conceitos de forma clara e acessivel
- Citar informacoes tecnicas quando relevante

ANALISE DE MIDIA:
- Quando receber ANALISE DE MIDIA, use essas informacoes para complementar sua avaliacao
- Imagens: Considere os sinais visuais descritos na analise
- Audios: A transcricao do audio do tutor esta incluida
- Se a midia mostrar sinais preocupantes, enfatize a urgencia
- Se precisar de mais detalhes visuais, pode sugerir que enviem outra foto

FORMATO DE RESPOSTA:
- Seja claro, objetivo e empatico
- Use linguagem acessivel ao tutor do animal
- Sempre termine recomendando consulta presencial se necessario
- Em emergencias, enfatize a necessidade de atendimento IMEDIATO"""

        if context:
            return f"""{base_prompt}

---
CONTEXTO TECNICO (use estas informacoes para embasar sua resposta):

{context}
---

Baseie sua resposta no contexto tecnico acima, mas mantenha linguagem acessivel."""
        
        return base_prompt
    
    async def process_message(
        self,
        user_id: str,
        message: str,
        use_knowledge: bool = True,
        retrieval_mode: Optional[RetrievalMode] = None,
        media_description: Optional[str] = None,
        use_memory: bool = True
    ) -> str:
        """
        Processa mensagem do usuario com RAG via MCP, mídia e memória.
        
        Args:
            user_id: ID do usuario
            message: Mensagem recebida
            use_knowledge: Se deve buscar na base via MCP
            retrieval_mode: Modo de recuperação (vector, structural, auto)
            media_description: Descrição/análise de mídia enviada
            use_memory: Se deve usar histórico da conversa
            
        Returns:
            Resposta do agente
        """
        try:
            context = ""
            mode = retrieval_mode or self.default_retrieval_mode
            
            # Adicionar análise de mídia ao contexto
            if media_description:
                context = f"[ANÁLISE DE MÍDIA ENVIADA PELO TUTOR]\n{media_description}\n\n"
                logger.info(f"Mídia processada para {user_id}: {media_description[:100]}...")
            
            # Buscar contexto via MCP Client (padronizado)
            if use_knowledge:
                mcp_context = await self._get_context_via_mcp(message, mode)
                if mcp_context:
                    context += mcp_context
                    logger.info(f"Contexto MCP obtido ({len(mcp_context)} chars)")
            
            system_prompt = self._get_system_prompt(context)
            
            # Construir mensagens com histórico
            messages = [{"role": "system", "content": system_prompt}]
            
            # Adicionar histórico de conversa
            if use_memory:
                history = await conversation_memory.get_history_for_prompt(user_id, max_tokens=2000)
                if history:
                    messages.extend(history)
                    logger.info(f"Histórico carregado: {len(history)} mensagens")
            
            # Adicionar mensagem atual
            current_message = message
            if media_description:
                current_message = f"{message}\n\n[O tutor enviou uma imagem/mídia que foi analisada acima]"
            
            messages.append({"role": "user", "content": current_message})
            
            # Chamar OpenAI
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=800
            )
            
            agent_response = response.choices[0].message.content
            agent_response = self._apply_guardrails(agent_response)
            
            # Salvar no histórico
            if use_memory:
                await conversation_memory.add_message(
                    user_id=user_id,
                    role="user",
                    content=message,
                    has_media=bool(media_description),
                    media_type="image" if media_description else None
                )
                await conversation_memory.add_message(
                    user_id=user_id,
                    role="assistant",
                    content=agent_response
                )
            
            logger.info(f"Agente processou mensagem para {user_id}")
            return agent_response
            
        except Exception as e:
            logger.error(f"Erro no agente: {str(e)}", exc_info=True)
            return "Desculpe, ocorreu um erro. Por favor, tente novamente ou consulte um veterinario presencialmente."
    
    async def _get_context_via_mcp(self, query: str, mode: RetrievalMode) -> str:
        """
        Obtém contexto usando MCP Client.
        Todas as queries passam pelo MCP para padronização.
        
        Args:
            query: A pergunta do usuário
            mode: Modo de recuperação
            
        Returns:
            Contexto formatado do MCP
        """
        try:
            # Usar MCP Client para busca padronizada
            result = await mcp_client.search_veterinary_knowledge(
                query=query,
                mode=mode.value
            )
            
            if result.success:
                return result.content
            else:
                logger.warning(f"MCP query sem sucesso: {result.content}")
                return ""
                
        except Exception as e:
            logger.error(f"Erro ao obter contexto via MCP: {e}")
            return ""
    
    def _apply_guardrails(self, response: str) -> str:
        """Aplica guardrails de seguranca na resposta"""
        forbidden_patterns = [
            "diagnostico e",
            "tem a doenca",
            "esta com a doenca",
            "prescrevo",
            "tome este medicamento",
            "de este medicamento",
            "a dose e",
            "mg/kg",
            "ml por kg"
        ]
        
        response_lower = response.lower()
        for pattern in forbidden_patterns:
            if pattern in response_lower:
                logger.warning(f"Guardrail ativado: {pattern}")
                return """Entendo sua preocupacao. Para uma avaliacao adequada e segura, e fundamental que voce consulte um veterinario presencialmente. 

Somente um profissional pode examinar seu animal, fazer diagnosticos e prescrever tratamentos de forma segura.

Se for uma emergencia, procure atendimento veterinario imediatamente."""
        
        return response
    
    # ==================== MCP TOOLS EXPOSTAS ====================
    
    async def mcp_search(self, query: str, mode: str = "auto") -> MCPToolResult:
        """
        Busca via MCP - expõe search_veterinary_knowledge.
        Para uso externo/debug.
        """
        return await mcp_client.search_veterinary_knowledge(query, mode)
    
    async def mcp_vector_search(self, query: str, top_k: int = 5) -> MCPToolResult:
        """Busca vetorial via MCP"""
        return await mcp_client.vector_search(query, top_k)
    
    async def mcp_structural_navigate(self, query: str, max_steps: int = 5) -> MCPToolResult:
        """Navegação estrutural via MCP"""
        return await mcp_client.structural_navigate(query, max_steps)
    
    async def mcp_get_stats(self) -> MCPToolResult:
        """Estatísticas via MCP"""
        return await mcp_client.get_knowledge_stats()
    
    # ==================== UTILIDADES ====================
    
    def set_retrieval_mode(self, mode: RetrievalMode):
        """Define o modo padrão de recuperação"""
        self.default_retrieval_mode = mode
        logger.info(f"Modo de recuperação alterado para: {mode.value}")
    
    async def clear_conversation(self, user_id: str) -> bool:
        """Limpa o histórico de conversa de um usuário"""
        return await conversation_memory.clear_conversation(user_id)
    
    async def get_conversation_summary(self, user_id: str) -> Optional[str]:
        """Retorna resumo da conversa atual"""
        return await conversation_memory.get_summary(user_id)
