"""
Serviço de Navegação Estrutural para Base de Conhecimento
========================================================

Implementa RAG baseado em navegação hierárquica (estilo PageIndex) em vez de
busca vetorial. O LLM navega pela estrutura do documento como um humano faria.

Arquitetura:
- Documento → Capítulos → Seções → Páginas
- Navegação ativa em vez de recuperação passiva
- Sem necessidade de Vector DB (PostgreSQL puro)

Trade-offs:
- (+) Rastreabilidade lógica (referências cruzadas, anexos, tabelas)
- (+) Infraestrutura simples (só PostgreSQL)
- (-) Mais tokens de inferência
- (-) Requer múltiplas chamadas ao LLM para navegação
"""
import os
import re
import logging
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum

from pypdf import PdfReader
from openai import OpenAI

from app.config import settings
from app.infra.db import get_db_connection
from app.infra.cache import KnowledgeCache, cached

logger = logging.getLogger(__name__)


class NodeType(str, Enum):
    """Tipos de nós na árvore de documentos"""
    DOCUMENT = "document"
    CHAPTER = "chapter"
    SECTION = "section"
    SUBSECTION = "subsection"
    PAGE = "page"
    APPENDIX = "appendix"  # Anexos
    TABLE = "table"
    FIGURE = "figure"


@dataclass
class DocumentNode:
    """Nó na árvore hierárquica do documento"""
    id: Optional[int] = None
    document_id: int = 0
    parent_id: Optional[int] = None
    node_type: NodeType = NodeType.PAGE
    title: str = ""
    content: str = ""
    page_start: int = 0
    page_end: int = 0
    level: int = 0  # Profundidade na árvore
    order_index: int = 0  # Ordem entre irmãos
    references: List[str] = field(default_factory=list)  # Referências a outros nós
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def summary(self) -> str:
        """Resumo curto para navegação"""
        content_preview = self.content[:200] + "..." if len(self.content) > 200 else self.content
        return f"[{self.node_type.value}] {self.title}\n{content_preview}"


class StructuralKnowledgeService:
    """
    Serviço de conhecimento baseado em navegação estrutural.
    
    Em vez de buscar por similaridade semântica, o sistema monta uma árvore
    hierárquica do documento e permite que o LLM navegue por ela.
    """
    
    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")
    
    # ==================== SETUP ====================
    
    async def create_tables(self):
        """Cria tabelas necessárias para navegação estrutural"""
        db = await get_db_connection()
        
        # Tabela de documentos
        await db.execute("""
            CREATE TABLE IF NOT EXISTS structural_documents (
                document_id SERIAL PRIMARY KEY,
                file_name VARCHAR(255) NOT NULL,
                file_hash VARCHAR(64) UNIQUE NOT NULL,
                title TEXT,
                total_pages INTEGER,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata JSONB DEFAULT '{}'
            )
        """)
        
        # Tabela de nós hierárquicos (árvore)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS structural_nodes (
                node_id SERIAL PRIMARY KEY,
                document_id INTEGER REFERENCES structural_documents(document_id) ON DELETE CASCADE,
                parent_id INTEGER REFERENCES structural_nodes(node_id) ON DELETE CASCADE,
                node_type VARCHAR(50) NOT NULL,
                title TEXT NOT NULL,
                content TEXT,
                page_start INTEGER,
                page_end INTEGER,
                level INTEGER DEFAULT 0,
                order_index INTEGER DEFAULT 0,
                references TEXT[],
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Índices para navegação eficiente
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_structural_nodes_document ON structural_nodes(document_id);
            CREATE INDEX IF NOT EXISTS idx_structural_nodes_parent ON structural_nodes(parent_id);
            CREATE INDEX IF NOT EXISTS idx_structural_nodes_type ON structural_nodes(node_type);
            CREATE INDEX IF NOT EXISTS idx_structural_nodes_level ON structural_nodes(level);
        """)
        
        # Tabela de sumário (TOC) - cache para navegação rápida
        await db.execute("""
            CREATE TABLE IF NOT EXISTS structural_toc (
                toc_id SERIAL PRIMARY KEY,
                document_id INTEGER REFERENCES structural_documents(document_id) ON DELETE CASCADE,
                toc_text TEXT NOT NULL,
                toc_json JSONB NOT NULL
            )
        """)
        
        logger.info("Tabelas de estrutura hierárquica criadas")
    
    # ==================== INGESTÃO ====================
    
    async def ingest_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """
        Processa um PDF extraindo sua estrutura hierárquica.
        
        Diferente do chunking tradicional, aqui extraímos:
        - Sumário/índice (se existir)
        - Hierarquia de títulos (detectados por fonte/padrão)
        - Conteúdo de cada seção
        - Referências cruzadas (Anexos, Tabelas, Figuras)
        """
        logger.info(f"Processando estrutura do PDF: {pdf_path}")
        
        import hashlib
        with open(pdf_path, "rb") as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        
        db = await get_db_connection()
        
        # Verificar se já processado
        existing = await db.fetchval(
            "SELECT document_id FROM structural_documents WHERE file_hash = $1",
            file_hash
        )
        if existing:
            return {"status": "already_processed", "document_id": existing}
        
        # Extrair texto e estrutura
        reader = PdfReader(pdf_path)
        filename = Path(pdf_path).name
        
        # Criar documento
        document_id = await db.fetchval("""
            INSERT INTO structural_documents (file_name, file_hash, total_pages)
            VALUES ($1, $2, $3)
            RETURNING document_id
        """, filename, file_hash, len(reader.pages))
        
        # Extrair estrutura
        nodes = self._extract_structure(reader)
        
        # Salvar nós
        saved = 0
        node_id_map = {}  # Para mapear índices temporários para IDs reais
        
        for node in nodes:
            parent_db_id = node_id_map.get(node.parent_id) if node.parent_id else None
            
            node_id = await db.fetchval("""
                INSERT INTO structural_nodes 
                (document_id, parent_id, node_type, title, content, page_start, page_end, 
                 level, order_index, references, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING node_id
            """, document_id, parent_db_id, node.node_type.value, node.title,
                node.content, node.page_start, node.page_end, node.level,
                node.order_index, node.references, "{}")
            
            node_id_map[node.order_index] = node_id
            saved += 1
        
        # Gerar e salvar sumário
        toc = await self._generate_toc(document_id)
        
        logger.info(f"Estrutura extraída: {saved} nós de {filename}")
        
        # Invalidar cache após nova ingestão
        await KnowledgeCache.invalidate_on_ingest()
        
        return {
            "status": "success",
            "document_id": document_id,
            "file": filename,
            "total_nodes": saved,
            "total_pages": len(reader.pages)
        }
    
    def _extract_structure(self, reader: PdfReader) -> List[DocumentNode]:
        """
        Extrai estrutura hierárquica do PDF.
        
        Estratégias:
        1. Usar outline/bookmarks do PDF (se existir)
        2. Detectar títulos por padrões de texto
        3. Detectar anexos, tabelas, figuras
        """
        nodes = []
        
        # Tentar usar outline do PDF primeiro
        if reader.outline:
            nodes = self._extract_from_outline(reader)
        
        # Se não houver outline, detectar por padrões
        if not nodes:
            nodes = self._extract_by_patterns(reader)
        
        return nodes
    
    def _extract_from_outline(self, reader: PdfReader) -> List[DocumentNode]:
        """Extrai estrutura do outline/bookmarks do PDF"""
        nodes = []
        order = 0
        
        def process_outline(items, parent_idx=None, level=0):
            nonlocal order
            
            for item in items:
                if isinstance(item, list):
                    # Lista aninhada = filhos do último item
                    if nodes:
                        process_outline(item, nodes[-1].order_index, level + 1)
                else:
                    # Item do outline
                    title = item.title if hasattr(item, 'title') else str(item)
                    page_num = 0
                    
                    # Determinar tipo do nó pelo título
                    node_type = self._detect_node_type(title, level)
                    
                    try:
                        if hasattr(item, 'page') and item.page:
                            page_num = reader.get_page_number(item.page) + 1
                    except:
                        pass
                    
                    node = DocumentNode(
                        parent_id=parent_idx,
                        node_type=node_type,
                        title=title,
                        content="",  # Será preenchido depois
                        page_start=page_num,
                        page_end=page_num,
                        level=level,
                        order_index=order
                    )
                    nodes.append(node)
                    order += 1
        
        process_outline(reader.outline)
        
        # Preencher conteúdo de cada nó
        self._fill_node_contents(nodes, reader)
        
        return nodes
    
    def _extract_by_patterns(self, reader: PdfReader) -> List[DocumentNode]:
        """Extrai estrutura detectando padrões de títulos no texto"""
        nodes = []
        
        # Padrões comuns de títulos
        patterns = {
            NodeType.CHAPTER: [
                r'^CAPÍTULO\s+(\d+|[IVXLCDM]+)',
                r'^CHAPTER\s+(\d+|[IVXLCDM]+)',
                r'^(\d+)\.\s+[A-Z][A-Z\s]+$',
            ],
            NodeType.SECTION: [
                r'^(\d+\.\d+)\s+',
                r'^SEÇÃO\s+(\d+)',
                r'^SECTION\s+(\d+)',
            ],
            NodeType.SUBSECTION: [
                r'^(\d+\.\d+\.\d+)\s+',
            ],
            NodeType.APPENDIX: [
                r'^ANEXO\s+([A-Z]|\d+)',
                r'^APPENDIX\s+([A-Z]|\d+)',
                r'^APÊNDICE\s+([A-Z]|\d+)',
            ],
            NodeType.TABLE: [
                r'^TABELA\s+(\d+)',
                r'^TABLE\s+(\d+)',
            ],
            NodeType.FIGURE: [
                r'^FIGURA\s+(\d+)',
                r'^FIGURE\s+(\d+)',
            ],
        }
        
        order = 0
        current_chapter_idx = None
        current_section_idx = None
        
        for page_num, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            lines = text.split('\n')
            
            page_content = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                matched = False
                
                for node_type, type_patterns in patterns.items():
                    for pattern in type_patterns:
                        if re.match(pattern, line, re.IGNORECASE):
                            # Determinar parent baseado no tipo
                            parent_idx = None
                            level = 0
                            
                            if node_type == NodeType.CHAPTER:
                                current_chapter_idx = order
                                level = 1
                            elif node_type == NodeType.SECTION:
                                parent_idx = current_chapter_idx
                                current_section_idx = order
                                level = 2
                            elif node_type == NodeType.SUBSECTION:
                                parent_idx = current_section_idx
                                level = 3
                            elif node_type in [NodeType.APPENDIX, NodeType.TABLE, NodeType.FIGURE]:
                                level = 1
                            
                            node = DocumentNode(
                                parent_id=parent_idx,
                                node_type=node_type,
                                title=line,
                                content="",
                                page_start=page_num,
                                page_end=page_num,
                                level=level,
                                order_index=order
                            )
                            nodes.append(node)
                            order += 1
                            matched = True
                            break
                    
                    if matched:
                        break
                
                if not matched:
                    page_content.append(line)
            
            # Se não encontrou estrutura, criar nó de página
            if not any(n.page_start == page_num for n in nodes):
                node = DocumentNode(
                    node_type=NodeType.PAGE,
                    title=f"Página {page_num}",
                    content='\n'.join(page_content),
                    page_start=page_num,
                    page_end=page_num,
                    level=0,
                    order_index=order
                )
                nodes.append(node)
                order += 1
        
        # Preencher conteúdo
        self._fill_node_contents(nodes, reader)
        
        return nodes
    
    def _detect_node_type(self, title: str, level: int) -> NodeType:
        """Detecta tipo do nó pelo título"""
        title_upper = title.upper()
        
        if any(x in title_upper for x in ['CAPÍTULO', 'CHAPTER', 'PARTE', 'PART']):
            return NodeType.CHAPTER
        elif any(x in title_upper for x in ['ANEXO', 'APPENDIX', 'APÊNDICE']):
            return NodeType.APPENDIX
        elif any(x in title_upper for x in ['TABELA', 'TABLE', 'QUADRO']):
            return NodeType.TABLE
        elif any(x in title_upper for x in ['FIGURA', 'FIGURE', 'IMAGEM']):
            return NodeType.FIGURE
        elif level == 0:
            return NodeType.DOCUMENT
        elif level == 1:
            return NodeType.CHAPTER
        elif level == 2:
            return NodeType.SECTION
        elif level >= 3:
            return NodeType.SUBSECTION
        
        return NodeType.SECTION
    
    def _fill_node_contents(self, nodes: List[DocumentNode], reader: PdfReader):
        """Preenche o conteúdo de cada nó baseado nas páginas"""
        if not nodes:
            return
        
        # Ordenar por página inicial
        sorted_nodes = sorted(nodes, key=lambda n: (n.page_start, n.order_index))
        
        for i, node in enumerate(sorted_nodes):
            # Determinar página final
            if i + 1 < len(sorted_nodes):
                next_node = sorted_nodes[i + 1]
                node.page_end = max(node.page_start, next_node.page_start - 1)
            else:
                node.page_end = len(reader.pages)
            
            # Extrair conteúdo
            content_parts = []
            for page_num in range(node.page_start - 1, min(node.page_end, len(reader.pages))):
                text = reader.pages[page_num].extract_text()
                if text:
                    content_parts.append(text)
            
            node.content = '\n'.join(content_parts)
            
            # Detectar referências cruzadas no conteúdo
            node.references = self._extract_references(node.content)
    
    def _extract_references(self, text: str) -> List[str]:
        """Extrai referências a outros nós (Anexos, Tabelas, etc.)"""
        references = []
        
        patterns = [
            r'(?:ver|veja|confira|conforme)\s+(anexo|tabela|figura|seção|capítulo)\s+(\w+)',
            r'(?:no|na|do|da)\s+(anexo|tabela|figura)\s+(\w+)',
            r'(anexo|tabela|figura)\s+(\w+)\s+(?:abaixo|acima|anterior|seguinte)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                ref = f"{match[0]} {match[1]}".upper()
                if ref not in references:
                    references.append(ref)
        
        return references
    
    async def _generate_toc(self, document_id: int) -> Dict:
        """Gera sumário estruturado do documento"""
        db = await get_db_connection()
        
        nodes = await db.fetch("""
            SELECT node_id, node_type, title, page_start, level, parent_id
            FROM structural_nodes
            WHERE document_id = $1
            ORDER BY order_index
        """, document_id)
        
        toc_lines = []
        toc_json = {"document_id": document_id, "items": []}
        
        for node in nodes:
            indent = "  " * node['level']
            toc_lines.append(f"{indent}{node['title']} (p.{node['page_start']})")
            
            toc_json["items"].append({
                "node_id": node['node_id'],
                "type": node['node_type'],
                "title": node['title'],
                "page": node['page_start'],
                "level": node['level']
            })
        
        toc_text = '\n'.join(toc_lines)
        
        # Salvar
        await db.execute("""
            INSERT INTO structural_toc (document_id, toc_text, toc_json)
            VALUES ($1, $2, $3)
            ON CONFLICT (document_id) DO UPDATE SET toc_text = $2, toc_json = $3
        """, document_id, toc_text, str(toc_json))
        
        return toc_json
    
    # ==================== NAVEGAÇÃO ====================
    
    async def navigate(self, query: str, max_steps: int = 5) -> Dict[str, Any]:
        """
        Navega pela estrutura do documento para responder uma query.
        
        O LLM lê o sumário, decide qual caminho seguir, e pode fazer
        múltiplos saltos até encontrar a informação.
        
        Returns:
            Dict com caminho de navegação e conteúdo encontrado
        """
        # Verificar cache primeiro
        cached_result = await KnowledgeCache.get(
            "structural_navigation", query, max_steps=max_steps
        )
        if cached_result:
            logger.info(f"Navegação estrutural retornada do cache: {query[:50]}...")
            return cached_result
        
        db = await get_db_connection()
        
        # Obter sumário de todos os documentos
        tocs = await db.fetch("""
            SELECT d.document_id, d.file_name, d.title, t.toc_text
            FROM structural_documents d
            LEFT JOIN structural_toc t ON d.document_id = t.document_id
        """)
        
        if not tocs:
            return {"error": "Nenhum documento indexado"}
        
        # Montar visão geral para o navegador
        overview = "DOCUMENTOS DISPONÍVEIS:\n\n"
        for toc in tocs:
            overview += f"📄 {toc['file_name']}\n"
            if toc['toc_text']:
                overview += f"{toc['toc_text'][:1000]}...\n\n" if len(toc['toc_text']) > 1000 else f"{toc['toc_text']}\n\n"
        
        # Agente de navegação
        navigation_log = []
        content_found = []
        
        for step in range(max_steps):
            # Decidir próximo passo
            decision = await self._navigation_step(
                query=query,
                overview=overview,
                navigation_log=navigation_log,
                content_found=content_found
            )
            
            if decision['action'] == 'DONE':
                break
            
            elif decision['action'] == 'NAVIGATE':
                # Navegar para um nó específico
                node = await self._get_node_by_title(decision['target'])
                if node:
                    navigation_log.append(f"Navegou para: {node['title']}")
                    content_found.append({
                        "title": node['title'],
                        "type": node['node_type'],
                        "content": node['content'][:2000],  # Limitar tamanho
                        "page": node['page_start']
                    })
                    
                    # Se tem referências, adicionar ao contexto
                    if node['references']:
                        navigation_log.append(f"Referências encontradas: {node['references']}")
            
            elif decision['action'] == 'FOLLOW_REFERENCE':
                # Seguir uma referência cruzada
                ref_node = await self._get_node_by_reference(decision['target'])
                if ref_node:
                    navigation_log.append(f"Seguiu referência para: {ref_node['title']}")
                    content_found.append({
                        "title": ref_node['title'],
                        "type": ref_node['node_type'],
                        "content": ref_node['content'][:2000],
                        "page": ref_node['page_start']
                    })
        
        result = {
            "query": query,
            "navigation_path": navigation_log,
            "content": content_found,
            "steps": len(navigation_log)
        }
        
        # Cachear resultado
        await KnowledgeCache.set(
            "structural_navigation", query, result, max_steps=max_steps
        )
        
        return result
    
    async def _navigation_step(
        self,
        query: str,
        overview: str,
        navigation_log: List[str],
        content_found: List[Dict]
    ) -> Dict[str, str]:
        """
        Um passo de navegação. O LLM decide o que fazer.
        """
        prompt = f"""Você é um agente de navegação de documentos técnicos.

QUERY DO USUÁRIO:
{query}

ESTRUTURA DOS DOCUMENTOS:
{overview}

NAVEGAÇÃO ATÉ AGORA:
{chr(10).join(navigation_log) if navigation_log else "Nenhuma navegação ainda"}

CONTEÚDO JÁ ENCONTRADO:
{chr(10).join([f"- {c['title']}: {c['content'][:200]}..." for c in content_found]) if content_found else "Nenhum"}

Decida a próxima ação:
1. NAVIGATE <título da seção> - Ir para uma seção específica
2. FOLLOW_REFERENCE <referência> - Seguir uma referência cruzada (ex: Anexo G)
3. DONE - Informação suficiente encontrada

Responda APENAS com a ação no formato:
ACTION: <ação>
TARGET: <alvo se aplicável>
REASON: <breve justificativa>"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200
        )
        
        text = response.choices[0].message.content
        
        # Parser da resposta
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
    
    async def _get_node_by_title(self, title: str) -> Optional[Dict]:
        """Busca nó por título (busca fuzzy)"""
        db = await get_db_connection()
        
        # Tentar match exato primeiro
        node = await db.fetchrow("""
            SELECT * FROM structural_nodes
            WHERE LOWER(title) = LOWER($1)
            LIMIT 1
        """, title)
        
        if node:
            return dict(node)
        
        # Busca fuzzy
        node = await db.fetchrow("""
            SELECT * FROM structural_nodes
            WHERE LOWER(title) LIKE LOWER($1)
            LIMIT 1
        """, f"%{title}%")
        
        return dict(node) if node else None
    
    async def _get_node_by_reference(self, reference: str) -> Optional[Dict]:
        """Busca nó por referência (ex: 'Anexo G')"""
        db = await get_db_connection()
        
        # Normalizar referência
        ref_upper = reference.upper()
        
        node = await db.fetchrow("""
            SELECT * FROM structural_nodes
            WHERE UPPER(title) LIKE $1
            OR node_type = $2
            LIMIT 1
        """, f"%{ref_upper}%", ref_upper.split()[0].lower() if ' ' in ref_upper else 'appendix')
        
        return dict(node) if node else None
    
    # ==================== QUERY COM NAVEGAÇÃO ====================
    
    async def get_context_for_query(self, query: str) -> str:
        """
        Obtém contexto relevante usando navegação estrutural.
        
        Esta é a função principal para integrar com o VetAgent.
        Retorna o contexto formatado para usar no prompt.
        """
        result = await self.navigate(query)
        
        if 'error' in result:
            return ""
        
        if not result['content']:
            return ""
        
        # Formatar contexto
        context_parts = []
        context_parts.append(f"[Navegação: {' → '.join(result['navigation_path'])}]")
        
        for item in result['content']:
            context_parts.append(f"""
📍 {item['title']} (p.{item['page']})
{item['content']}
""")
        
        return '\n'.join(context_parts)
    
    # ==================== UTILITÁRIOS ====================
    
    async def get_stats(self) -> Dict:
        """Estatísticas da base estrutural"""
        db = await get_db_connection()
        
        docs = await db.fetch("""
            SELECT d.document_id, d.file_name, d.total_pages,
                   COUNT(n.node_id) as total_nodes
            FROM structural_documents d
            LEFT JOIN structural_nodes n ON d.document_id = n.document_id
            GROUP BY d.document_id
        """)
        
        node_types = await db.fetch("""
            SELECT node_type, COUNT(*) as count
            FROM structural_nodes
            GROUP BY node_type
        """)
        
        return {
            "documents": [dict(d) for d in docs],
            "node_types": {n['node_type']: n['count'] for n in node_types},
            "total_documents": len(docs),
            "total_nodes": sum(d['total_nodes'] for d in docs)
        }
    
    async def get_document_tree(self, document_id: int) -> Dict:
        """Retorna árvore completa de um documento"""
        db = await get_db_connection()
        
        nodes = await db.fetch("""
            SELECT * FROM structural_nodes
            WHERE document_id = $1
            ORDER BY order_index
        """, document_id)
        
        def build_tree(parent_id=None):
            children = []
            for node in nodes:
                if node['parent_id'] == parent_id:
                    children.append({
                        "id": node['node_id'],
                        "type": node['node_type'],
                        "title": node['title'],
                        "page": node['page_start'],
                        "children": build_tree(node['node_id'])
                    })
            return children
        
        return {"document_id": document_id, "tree": build_tree()}
    
    async def ingest_all_pdfs(self, folder_path: str = "knowledge") -> List[Dict]:
        """Processa todos os PDFs de uma pasta"""
        results = []
        folder = Path(folder_path)
        
        if not folder.exists():
            return [{"error": f"Pasta {folder_path} não encontrada"}]
        
        # Garantir que as tabelas existem
        await self.create_tables()
        
        pdf_files = list(folder.glob("*.pdf"))
        logger.info(f"Encontrados {len(pdf_files)} PDFs para processamento estrutural")
        
        for pdf_path in pdf_files:
            result = await self.ingest_pdf(str(pdf_path))
            results.append(result)
        
        return results


# Instância global
structural_knowledge_service = StructuralKnowledgeService()
