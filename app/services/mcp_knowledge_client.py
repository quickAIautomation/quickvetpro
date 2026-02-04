"""
Cliente MCP de Conhecimento
===========================

Interface padronizada para queries de conhecimento.
Expõe as mesmas tools do MCP Server para uso interno no VetAgent.

Todas as interações de conhecimento passam por aqui, garantindo:
- Padronização das queries
- Mesma lógica do MCP Server
- Cache unificado
- Logs centralizados
"""
import os
import logging
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass

from app.services.knowledge_service import knowledge_service
from app.services.structural_knowledge_service import structural_knowledge_service

logger = logging.getLogger(__name__)


class RetrievalMode(str, Enum):
    """Modos de recuperação - espelha o MCP Server"""
    VECTOR = "vector"
    STRUCTURAL = "structural"
    AUTO = "auto"


@dataclass
class MCPToolResult:
    """Resultado padronizado de uma tool MCP"""
    success: bool
    content: str
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class MCPKnowledgeClient:
    """
    Cliente que espelha as tools do MCP Server.
    
    Garante que o VetAgent use a mesma interface e lógica
    que clientes externos (Cursor) usam via MCP.
    
    Tools disponíveis:
    - search_veterinary_knowledge (auto/vector/structural)
    - vector_search
    - structural_navigate
    - get_knowledge_stats
    """
    
    # Keywords que ativam modo estrutural
    STRUCTURAL_KEYWORDS = [
        'tabela', 'anexo', 'apêndice', 'quadro', 'figura',
        'protocolo', 'procedimento', 'passo a passo',
        'dose', 'dosagem', 'cálculo', 'fórmula',
        'valor', 'referência', 'limite', 'intervalo',
        'seção', 'capítulo', 'página'
    ]
    
    def __init__(self):
        self.default_mode = RetrievalMode(os.getenv("RETRIEVAL_MODE", "auto"))
    
    # ==================== DETECÇÃO DE MODO ====================
    
    def detect_best_mode(self, query: str) -> RetrievalMode:
        """
        Detecta automaticamente o melhor modo de recuperação.
        Mesma lógica do MCP Server.
        """
        query_lower = query.lower()
        
        # Se menciona elementos estruturais
        if any(kw in query_lower for kw in self.STRUCTURAL_KEYWORDS):
            return RetrievalMode.STRUCTURAL
        
        # Queries complexas (>10 palavras)
        if len(query.split()) > 10:
            return RetrievalMode.STRUCTURAL
        
        return RetrievalMode.VECTOR
    
    # ==================== TOOLS MCP ====================
    
    async def search_veterinary_knowledge(
        self,
        query: str,
        mode: str = "auto"
    ) -> MCPToolResult:
        """
        Tool principal de busca - espelha MCP search_veterinary_knowledge.
        
        Args:
            query: Pergunta ou termo de busca
            mode: "auto", "vector" ou "structural"
            
        Returns:
            MCPToolResult com conteúdo formatado
        """
        try:
            # Detectar modo se auto
            if mode == "auto":
                detected_mode = self.detect_best_mode(query)
                logger.info(f"MCP: Modo AUTO detectou '{detected_mode.value}' para: {query[:50]}...")
            else:
                detected_mode = RetrievalMode(mode)
            
            # Executar busca apropriada
            if detected_mode == RetrievalMode.VECTOR:
                return await self.vector_search(query)
            else:
                return await self.structural_navigate(query)
                
        except Exception as e:
            logger.error(f"MCP search_veterinary_knowledge erro: {e}")
            return MCPToolResult(
                success=False,
                content=f"Erro na busca: {str(e)}"
            )
    
    async def vector_search(
        self,
        query: str,
        top_k: int = 5
    ) -> MCPToolResult:
        """
        Busca vetorial - espelha MCP vector_search.
        
        Args:
            query: Pergunta ou termo de busca
            top_k: Número de resultados
            
        Returns:
            MCPToolResult com chunks encontrados
        """
        try:
            logger.info(f"MCP vector_search: {query[:50]}...")
            
            results = await knowledge_service.search(query, top_k)
            
            if not results:
                return MCPToolResult(
                    success=True,
                    content="Nenhum resultado encontrado na busca vetorial.",
                    metadata={"mode": "vector", "results_count": 0}
                )
            
            # Formatar resultado como o MCP Server faz
            formatted = "\n\n".join([
                f"[{i+1}] (Similaridade: {r['similarity']*100:.1f}%)\n📄 {r['file']}\n{r['content'][:500]}..."
                for i, r in enumerate(results)
            ])
            
            content = f"🔍 *Busca Vetorial* - {len(results)} resultados:\n\n{formatted}"
            
            return MCPToolResult(
                success=True,
                content=content,
                metadata={
                    "mode": "vector",
                    "results_count": len(results),
                    "results": results
                }
            )
            
        except Exception as e:
            logger.error(f"MCP vector_search erro: {e}")
            return MCPToolResult(
                success=False,
                content=f"Erro na busca vetorial: {str(e)}"
            )
    
    async def structural_navigate(
        self,
        query: str,
        max_steps: int = 5
    ) -> MCPToolResult:
        """
        Navegação estrutural - espelha MCP structural_navigate.
        
        Args:
            query: Pergunta detalhada
            max_steps: Máximo de passos de navegação
            
        Returns:
            MCPToolResult com caminho de navegação e conteúdo
        """
        try:
            logger.info(f"MCP structural_navigate: {query[:50]}...")
            
            result = await structural_knowledge_service.navigate(query, max_steps)
            
            if "error" in result:
                return MCPToolResult(
                    success=False,
                    content=f"Erro na navegação: {result['error']}"
                )
            
            if not result.get("content"):
                return MCPToolResult(
                    success=True,
                    content="Nenhum conteúdo encontrado na navegação estrutural.",
                    metadata={"mode": "structural", "steps": 0}
                )
            
            # Formatar resultado como o MCP Server faz
            path = " → ".join(result["navigation_path"]) if result["navigation_path"] else "Direto"
            
            content_text = "\n\n".join([
                f"📍 *{c['title']}* (p.{c['page']})\nTipo: {c['type']}\n{c['content'][:600]}..."
                for c in result["content"]
            ])
            
            content = f"🧭 *Navegação Estrutural* ({result['steps']} passos)\n\n📍 Caminho: {path}\n\n{content_text}"
            
            return MCPToolResult(
                success=True,
                content=content,
                metadata={
                    "mode": "structural",
                    "steps": result["steps"],
                    "navigation_path": result["navigation_path"],
                    "content": result["content"]
                }
            )
            
        except Exception as e:
            logger.error(f"MCP structural_navigate erro: {e}")
            return MCPToolResult(
                success=False,
                content=f"Erro na navegação estrutural: {str(e)}"
            )
    
    async def get_knowledge_stats(self) -> MCPToolResult:
        """
        Estatísticas - espelha MCP get_knowledge_stats.
        
        Returns:
            MCPToolResult com estatísticas da base
        """
        try:
            # Stats vetorial
            vector_stats = await knowledge_service.get_stats()
            
            # Stats estrutural
            structural_stats = await structural_knowledge_service.get_stats()
            
            # Formatar
            vector_files = "\n".join([
                f"  - {f['name']}: {f['chunks']} chunks"
                for f in vector_stats.get("files", [])
            ]) or "  Nenhum arquivo"
            
            structural_docs = "\n".join([
                f"  - {d['file_name']}: {d['total_pages']} páginas, {d['total_nodes']} nós"
                for d in structural_stats.get("documents", [])
            ]) or "  Nenhum documento"
            
            content = f"""📊 Base de Conhecimento QuickVET

🔍 *RAG Vetorial*
- Total: {vector_stats.get('total_chunks', 0)} chunks
- Arquivos:
{vector_files}

🧭 *RAG Estrutural (PageIndex)*
- Total: {structural_stats.get('total_documents', 0)} documentos
- Documentos:
{structural_docs}"""
            
            return MCPToolResult(
                success=True,
                content=content,
                metadata={
                    "vector": vector_stats,
                    "structural": structural_stats
                }
            )
            
        except Exception as e:
            logger.error(f"MCP get_knowledge_stats erro: {e}")
            return MCPToolResult(
                success=False,
                content=f"Erro ao obter estatísticas: {str(e)}"
            )
    
    # ==================== MÉTODO PRINCIPAL PARA AGENTE ====================
    
    async def get_context_for_query(
        self,
        query: str,
        mode: str = "auto",
        max_tokens: int = 3000
    ) -> str:
        """
        Método principal para o VetAgent obter contexto.
        
        Usa as tools MCP internamente e retorna contexto formatado
        para usar no prompt do agente.
        
        Args:
            query: Pergunta do usuário
            mode: Modo de busca
            max_tokens: Limite aproximado de tokens
            
        Returns:
            Contexto formatado para o prompt
        """
        result = await self.search_veterinary_knowledge(query, mode)
        
        if not result.success:
            logger.warning(f"MCP query falhou: {result.content}")
            return ""
        
        # Limitar tamanho do contexto
        content = result.content
        if len(content) > max_tokens * 4:  # ~4 chars por token
            content = content[:max_tokens * 4] + "\n\n[...contexto truncado...]"
        
        return content


# Instância global
mcp_client = MCPKnowledgeClient()
