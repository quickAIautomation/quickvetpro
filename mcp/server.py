"""
QuickVET MCP Server - Base de Conhecimento Veterinária
======================================================

Servidor MCP com dois modos de RAG:
1. Busca Vetorial (embeddings) - rápido, similaridade semântica
2. Navegação Estrutural (PageIndex) - preciso, rastreabilidade lógica

O modo AUTO detecta automaticamente qual usar baseado na query.
"""
import os
import sys
import json
import hashlib
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

# MCP SDK
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    Resource,
)

# PDF e Embeddings
from pypdf import PdfReader
from openai import OpenAI

# Database
import asyncpg
import asyncio

# Configurações
EMBEDDING_MODEL = "text-embedding-3-small"
DB_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/quickvet")
KNOWLEDGE_FOLDER = Path(__file__).parent.parent / "knowledge"


class RetrievalMode(str, Enum):
    """Modos de recuperação"""
    VECTOR = "vector"
    STRUCTURAL = "structural"
    AUTO = "auto"


@dataclass
class NavigationStep:
    """Um passo na navegação estrutural"""
    action: str
    target: str
    reason: str


class KnowledgeBase:
    """
    Base de conhecimento com dois modos de RAG:
    - Vetorial: busca por similaridade semântica
    - Estrutural: navegação hierárquica estilo PageIndex
    """
    
    def __init__(self):
        self.openai = None
        self.db_pool = None
        
    async def initialize(self):
        """Inicializa conexões"""
        # OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            self.openai = OpenAI(api_key=api_key)
        
        # PostgreSQL
        try:
            self.db_pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=10)
        except Exception as e:
            print(f"Aviso: Não foi possível conectar ao PostgreSQL: {e}")
            print("Algumas funcionalidades estarão desabilitadas.")
    
    async def close(self):
        """Fecha conexões"""
        if self.db_pool:
            await self.db_pool.close()
    
    # ==================== DETECÇÃO DE MODO ====================
    
    def detect_best_mode(self, query: str) -> RetrievalMode:
        """
        Detecta automaticamente o melhor modo de recuperação.
        
        Usa ESTRUTURAL quando:
        - Menciona tabelas, anexos, apêndices
        - Pede dados específicos (números, valores)
        - Query é complexa (>10 palavras)
        
        Usa VETORIAL quando:
        - Query é simples/conceitual
        - Busca definições
        """
        structural_keywords = [
            'tabela', 'anexo', 'apêndice', 'quadro', 'figura',
            'protocolo', 'procedimento', 'passo a passo',
            'dose', 'dosagem', 'cálculo', 'fórmula',
            'valor', 'referência', 'limite', 'intervalo',
            'seção', 'capítulo', 'página'
        ]
        
        query_lower = query.lower()
        
        if any(kw in query_lower for kw in structural_keywords):
            return RetrievalMode.STRUCTURAL
        
        if len(query.split()) > 10:
            return RetrievalMode.STRUCTURAL
        
        return RetrievalMode.VECTOR
    
    # ==================== BUSCA VETORIAL ====================
    
    async def vector_search(self, query: str, top_k: int = 5) -> List[Dict]:
        """Busca por similaridade semântica usando embeddings"""
        if not self.db_pool:
            return [{"error": "Banco de dados não disponível"}]
        
        if not self.openai:
            return await self._text_search(query, top_k)
        
        try:
            # Gerar embedding da query
            response = self.openai.embeddings.create(
                model=EMBEDDING_MODEL,
                input=query
            )
            query_embedding = response.data[0].embedding
            embedding_str = f"[{','.join(map(str, query_embedding))}]"
            
            # Buscar no PostgreSQL com pgvector
            async with self.db_pool.acquire() as conn:
                results = await conn.fetch("""
                    SELECT 
                        content,
                        file_name,
                        chunk_index,
                        1 - (embedding <=> $1::vector) as similarity
                    FROM knowledge_chunks
                    ORDER BY embedding <=> $1::vector
                    LIMIT $2
                """, embedding_str, top_k)
                
                return [
                    {
                        "content": r["content"],
                        "file": r["file_name"],
                        "chunk": r["chunk_index"],
                        "similarity": float(r["similarity"])
                    }
                    for r in results
                ]
                
        except Exception as e:
            return [{"error": str(e)}]
    
    async def _text_search(self, query: str, top_k: int) -> List[Dict]:
        """Busca simples por texto quando embeddings não disponíveis"""
        if not self.db_pool:
            return []
        
        try:
            words = query.lower().split()
            
            async with self.db_pool.acquire() as conn:
                # Buscar chunks que contêm as palavras
                results = await conn.fetch("""
                    SELECT content, file_name, chunk_index
                    FROM knowledge_chunks
                    WHERE LOWER(content) LIKE $1
                    LIMIT $2
                """, f"%{words[0]}%", top_k * 2)
                
                # Rankear por quantidade de palavras encontradas
                ranked = []
                for r in results:
                    content_lower = r["content"].lower()
                    matches = sum(1 for w in words if w in content_lower)
                    ranked.append({
                        "content": r["content"],
                        "file": r["file_name"],
                        "chunk": r["chunk_index"],
                        "similarity": matches / len(words)
                    })
                
                ranked.sort(key=lambda x: x["similarity"], reverse=True)
                return ranked[:top_k]
                
        except Exception as e:
            return [{"error": str(e)}]
    
    # ==================== NAVEGAÇÃO ESTRUTURAL ====================
    
    async def structural_navigate(self, query: str, max_steps: int = 5) -> Dict:
        """
        Navega pela estrutura hierárquica do documento.
        
        O LLM lê o sumário, decide qual caminho seguir, e pode fazer
        múltiplos saltos até encontrar a informação.
        """
        if not self.db_pool:
            return {"error": "Banco de dados não disponível"}
        
        if not self.openai:
            return {"error": "OpenAI não configurada (necessária para navegação)"}
        
        try:
            async with self.db_pool.acquire() as conn:
                # Obter sumário de todos os documentos
                tocs = await conn.fetch("""
                    SELECT d.document_id, d.file_name, d.title, t.toc_text
                    FROM structural_documents d
                    LEFT JOIN structural_toc t ON d.document_id = t.document_id
                """)
                
                if not tocs:
                    return {"error": "Nenhum documento estruturado indexado. Use /api/structural/ingest primeiro."}
                
                # Montar visão geral
                overview = "DOCUMENTOS DISPONÍVEIS:\n\n"
                for toc in tocs:
                    overview += f"📄 {toc['file_name']}\n"
                    if toc['toc_text']:
                        toc_preview = toc['toc_text'][:1000] + "..." if len(toc['toc_text']) > 1000 else toc['toc_text']
                        overview += f"{toc_preview}\n\n"
                
                # Navegação iterativa
                navigation_log = []
                content_found = []
                
                for step in range(max_steps):
                    decision = await self._navigation_step(
                        query, overview, navigation_log, content_found, conn
                    )
                    
                    if decision["action"] == "DONE":
                        break
                    
                    elif decision["action"] == "NAVIGATE":
                        node = await self._get_node_by_title(conn, decision["target"])
                        if node:
                            navigation_log.append(f"Navegou para: {node['title']}")
                            content_found.append({
                                "title": node["title"],
                                "type": node["node_type"],
                                "content": node["content"][:2000] if node["content"] else "",
                                "page": node["page_start"]
                            })
                    
                    elif decision["action"] == "FOLLOW_REFERENCE":
                        ref_node = await self._get_node_by_reference(conn, decision["target"])
                        if ref_node:
                            navigation_log.append(f"Seguiu referência: {ref_node['title']}")
                            content_found.append({
                                "title": ref_node["title"],
                                "type": ref_node["node_type"],
                                "content": ref_node["content"][:2000] if ref_node["content"] else "",
                                "page": ref_node["page_start"]
                            })
                
                return {
                    "query": query,
                    "navigation_path": navigation_log,
                    "content": content_found,
                    "steps": len(navigation_log)
                }
                
        except Exception as e:
            return {"error": str(e)}
    
    async def _navigation_step(
        self,
        query: str,
        overview: str,
        navigation_log: List[str],
        content_found: List[Dict],
        conn
    ) -> Dict:
        """Um passo de navegação - LLM decide o que fazer"""
        
        prompt = f"""Você é um agente de navegação de documentos técnicos veterinários.

QUERY DO USUÁRIO:
{query}

ESTRUTURA DOS DOCUMENTOS:
{overview[:3000]}

NAVEGAÇÃO ATÉ AGORA:
{chr(10).join(navigation_log) if navigation_log else "Nenhuma navegação ainda"}

CONTEÚDO JÁ ENCONTRADO:
{chr(10).join([f"- {c['title']}: {c['content'][:200]}..." for c in content_found]) if content_found else "Nenhum"}

Decida a próxima ação:
1. NAVIGATE <título da seção> - Ir para uma seção específica
2. FOLLOW_REFERENCE <referência> - Seguir uma referência (ex: Anexo G, Tabela 3)
3. DONE - Informação suficiente encontrada

Responda APENAS no formato:
ACTION: <ação>
TARGET: <alvo se aplicável>
REASON: <breve justificativa>"""

        response = self.openai.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200
        )
        
        text = response.choices[0].message.content
        
        # Parser
        action = "DONE"
        target = ""
        
        for line in text.split('\n'):
            if line.startswith('ACTION:'):
                action_text = line.replace('ACTION:', '').strip()
                if 'NAVIGATE' in action_text:
                    action = 'NAVIGATE'
                elif 'FOLLOW_REFERENCE' in action_text:
                    action = 'FOLLOW_REFERENCE'
                else:
                    action = 'DONE'
            elif line.startswith('TARGET:'):
                target = line.replace('TARGET:', '').strip()
        
        return {"action": action, "target": target}
    
    async def _get_node_by_title(self, conn, title: str) -> Optional[Dict]:
        """Busca nó por título"""
        # Match exato
        node = await conn.fetchrow("""
            SELECT * FROM structural_nodes
            WHERE LOWER(title) = LOWER($1)
            LIMIT 1
        """, title)
        
        if node:
            return dict(node)
        
        # Match fuzzy
        node = await conn.fetchrow("""
            SELECT * FROM structural_nodes
            WHERE LOWER(title) LIKE LOWER($1)
            LIMIT 1
        """, f"%{title}%")
        
        return dict(node) if node else None
    
    async def _get_node_by_reference(self, conn, reference: str) -> Optional[Dict]:
        """Busca nó por referência (ex: 'Anexo G')"""
        ref_upper = reference.upper()
        
        node = await conn.fetchrow("""
            SELECT * FROM structural_nodes
            WHERE UPPER(title) LIKE $1
            LIMIT 1
        """, f"%{ref_upper}%")
        
        return dict(node) if node else None
    
    # ==================== BUSCA COMBINADA ====================
    
    async def smart_search(self, query: str, mode: str = "auto") -> Dict:
        """
        Busca inteligente que escolhe o melhor método.
        
        Args:
            query: A pergunta do usuário
            mode: "vector", "structural" ou "auto"
        """
        if mode == "auto":
            detected_mode = self.detect_best_mode(query)
        else:
            detected_mode = RetrievalMode(mode)
        
        if detected_mode == RetrievalMode.VECTOR:
            results = await self.vector_search(query)
            return {
                "mode": "vector",
                "results": results
            }
        else:
            result = await self.structural_navigate(query)
            return {
                "mode": "structural",
                "navigation": result
            }
    
    # ==================== ESTATÍSTICAS ====================
    
    async def get_stats(self) -> Dict:
        """Estatísticas da base de conhecimento"""
        if not self.db_pool:
            return {"error": "Banco de dados não disponível"}
        
        try:
            async with self.db_pool.acquire() as conn:
                # Chunks vetoriais
                vector_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM knowledge_chunks"
                )
                
                vector_files = await conn.fetch("""
                    SELECT file_name, COUNT(*) as chunks
                    FROM knowledge_chunks
                    GROUP BY file_name
                """)
                
                # Documentos estruturais
                structural_docs = await conn.fetch("""
                    SELECT d.file_name, d.total_pages, COUNT(n.node_id) as nodes
                    FROM structural_documents d
                    LEFT JOIN structural_nodes n ON d.document_id = n.document_id
                    GROUP BY d.document_id
                """)
                
                return {
                    "vector": {
                        "total_chunks": vector_count,
                        "files": [{"name": f["file_name"], "chunks": f["chunks"]} for f in vector_files]
                    },
                    "structural": {
                        "total_documents": len(structural_docs),
                        "documents": [
                            {"name": d["file_name"], "pages": d["total_pages"], "nodes": d["nodes"]}
                            for d in structural_docs
                        ]
                    }
                }
                
        except Exception as e:
            return {"error": str(e)}


# Instância global
kb = KnowledgeBase()

# Criar servidor MCP
server = Server("quickvet-knowledge")


@server.list_tools()
async def list_tools():
    """Lista de tools disponíveis"""
    return [
        Tool(
            name="search_veterinary_knowledge",
            description="""Busca inteligente na base de conhecimento veterinário.
            
Modos disponíveis:
- "auto" (padrão): Detecta automaticamente o melhor método
- "vector": Busca por similaridade semântica (rápido)
- "structural": Navegação hierárquica estilo PageIndex (preciso, para tabelas/anexos)

Use para perguntas sobre saúde animal, doenças, tratamentos, protocolos, etc.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Pergunta ou termo de busca"
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "vector", "structural"],
                        "description": "Modo de busca (padrão: auto)"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="vector_search",
            description="Busca por similaridade semântica (embeddings). Rápido, bom para conceitos gerais.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Pergunta ou termo de busca"
                    },
                    "top_k": {
                        "type": "number",
                        "description": "Número de resultados (padrão: 5)"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="structural_navigate",
            description="""Navegação hierárquica pelos documentos (estilo PageIndex).
            
Use quando:
- Precisa encontrar tabelas, anexos, apêndices
- Busca valores específicos, dosagens, protocolos
- Precisa seguir referências cruzadas (ex: "ver Anexo G")

Mais preciso que busca vetorial para queries complexas.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Pergunta detalhada"
                    },
                    "max_steps": {
                        "type": "number",
                        "description": "Máximo de passos de navegação (padrão: 5)"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_knowledge_stats",
            description="Retorna estatísticas da base de conhecimento (vetorial e estrutural)",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Executa uma tool"""
    try:
        if name == "search_veterinary_knowledge":
            query = arguments.get("query", "")
            mode = arguments.get("mode", "auto")
            
            result = await kb.smart_search(query, mode)
            
            if result["mode"] == "vector":
                if not result["results"]:
                    return [TextContent(type="text", text="Nenhum resultado encontrado.")]
                
                if "error" in result["results"][0]:
                    return [TextContent(type="text", text=f"Erro: {result['results'][0]['error']}")]
                
                formatted = "\n\n".join([
                    f"[{i+1}] (Similaridade: {r['similarity']*100:.1f}%)\n📄 {r['file']}\n{r['content'][:500]}..."
                    for i, r in enumerate(result["results"])
                ])
                
                return [TextContent(
                    type="text",
                    text=f"🔍 *Busca Vetorial* - {len(result['results'])} resultados:\n\n{formatted}"
                )]
            
            else:  # structural
                nav = result["navigation"]
                
                if "error" in nav:
                    return [TextContent(type="text", text=f"Erro: {nav['error']}")]
                
                path = " → ".join(nav["navigation_path"]) if nav["navigation_path"] else "Direto"
                
                content_text = "\n\n".join([
                    f"📍 *{c['title']}* (p.{c['page']})\n{c['content'][:500]}..."
                    for c in nav["content"]
                ]) if nav["content"] else "Nenhum conteúdo encontrado"
                
                return [TextContent(
                    type="text",
                    text=f"🧭 *Navegação Estrutural* ({nav['steps']} passos)\n\n📍 Caminho: {path}\n\n{content_text}"
                )]
        
        elif name == "vector_search":
            query = arguments.get("query", "")
            top_k = arguments.get("top_k", 5)
            
            results = await kb.vector_search(query, top_k)
            
            if not results:
                return [TextContent(type="text", text="Nenhum resultado encontrado.")]
            
            if "error" in results[0]:
                return [TextContent(type="text", text=f"Erro: {results[0]['error']}")]
            
            formatted = "\n\n".join([
                f"[{i+1}] (Similaridade: {r['similarity']*100:.1f}%)\n📄 {r['file']}\n{r['content'][:500]}..."
                for i, r in enumerate(results)
            ])
            
            return [TextContent(type="text", text=f"Encontrados {len(results)} resultados:\n\n{formatted}")]
        
        elif name == "structural_navigate":
            query = arguments.get("query", "")
            max_steps = arguments.get("max_steps", 5)
            
            result = await kb.structural_navigate(query, max_steps)
            
            if "error" in result:
                return [TextContent(type="text", text=f"Erro: {result['error']}")]
            
            path = " → ".join(result["navigation_path"]) if result["navigation_path"] else "Nenhuma navegação"
            
            content_text = "\n\n".join([
                f"📍 *{c['title']}* (p.{c['page']})\nTipo: {c['type']}\n{c['content'][:600]}..."
                for c in result["content"]
            ]) if result["content"] else "Nenhum conteúdo encontrado"
            
            return [TextContent(
                type="text",
                text=f"🧭 Navegação Estrutural\n\n📍 Caminho ({result['steps']} passos): {path}\n\n{content_text}"
            )]
        
        elif name == "get_knowledge_stats":
            stats = await kb.get_stats()
            
            if "error" in stats:
                return [TextContent(type="text", text=f"Erro: {stats['error']}")]
            
            vector_files = "\n".join([
                f"  - {f['name']}: {f['chunks']} chunks"
                for f in stats['vector']['files']
            ]) or "  Nenhum arquivo"
            
            structural_docs = "\n".join([
                f"  - {d['name']}: {d['pages']} páginas, {d['nodes']} nós"
                for d in stats['structural']['documents']
            ]) or "  Nenhum documento"
            
            return [TextContent(
                type="text",
                text=f"""📊 Base de Conhecimento QuickVET

🔍 *RAG Vetorial*
- Total: {stats['vector']['total_chunks']} chunks
- Arquivos:
{vector_files}

🧭 *RAG Estrutural (PageIndex)*
- Total: {stats['structural']['total_documents']} documentos
- Documentos:
{structural_docs}"""
            )]
        
        else:
            return [TextContent(type="text", text=f"Tool desconhecida: {name}")]
            
    except Exception as e:
        return [TextContent(type="text", text=f"Erro: {str(e)}")]


@server.list_resources()
async def list_resources():
    """Lista documentos como resources"""
    try:
        stats = await kb.get_stats()
        
        resources = []
        
        # Arquivos vetoriais
        for f in stats.get("vector", {}).get("files", []):
            resources.append(
                Resource(
                    uri=f"knowledge://vector/{f['name']}",
                    name=f"[Vetorial] {f['name']}",
                    description=f"PDF veterinário: {f['chunks']} chunks",
                    mimeType="text/plain"
                )
            )
        
        # Documentos estruturais
        for d in stats.get("structural", {}).get("documents", []):
            resources.append(
                Resource(
                    uri=f"knowledge://structural/{d['name']}",
                    name=f"[Estrutural] {d['name']}",
                    description=f"PDF com estrutura: {d['pages']} páginas, {d['nodes']} nós",
                    mimeType="text/plain"
                )
            )
        
        return resources
        
    except:
        return []


async def main():
    """Inicia o servidor MCP"""
    await kb.initialize()
    
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        await kb.close()


if __name__ == "__main__":
    asyncio.run(main())
