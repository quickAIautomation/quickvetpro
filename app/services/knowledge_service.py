"""
Serviço de Base de Conhecimento Veterinário
============================================

Implementa RAG (Retrieval-Augmented Generation) com pgvector.

Otimizações de performance:
- Cache de embeddings de query (evita recalcular)
- Busca assíncrona em batch (múltiplas queries paralelas)
- Índice HNSW no pgvector (busca 10-100x mais rápida)
- Cache de resultados com TTL configurável
"""
import os
import logging
import asyncio
from typing import List, Optional, Dict, Any
from pathlib import Path
import hashlib

from openai import OpenAI
from pypdf import PdfReader
import tiktoken

from app.config import settings
from app.infra.db import get_db_connection
from app.infra.cache import KnowledgeCache, EmbeddingCache

logger = logging.getLogger(__name__)

# Configurações
CHUNK_SIZE = 500  # tokens por chunk
CHUNK_OVERLAP = 50  # overlap entre chunks
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# Configurações de batch
BATCH_SIZE = 10  # Número de embeddings por chamada à API
MAX_CONCURRENT_BATCHES = 3  # Batches paralelos


class KnowledgeService:
    """
    Serviço para gerenciar base de conhecimento veterinária.
    
    Performance features:
    - Embedding cache: Não recalcula embeddings repetidos
    - Batch processing: Múltiplas queries processadas em paralelo
    - Result cache: Resultados de busca cacheados
    """
    
    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.tokenizer = tiktoken.encoding_for_model("gpt-4")
    
    # ==================== INGESTÃO ====================
    
    async def ingest_pdf(self, pdf_path: str) -> dict:
        """
        Processa um PDF e armazena os chunks com embeddings.
        Retorna estatísticas do processamento.
        """
        logger.info(f"Processando PDF: {pdf_path}")
        
        # Extrair texto
        text = self._extract_text_from_pdf(pdf_path)
        if not text:
            return {"error": "Não foi possível extrair texto do PDF"}
        
        # Criar chunks
        chunks = self._create_chunks(text)
        logger.info(f"Criados {len(chunks)} chunks")
        
        # Gerar embeddings e salvar
        saved = 0
        file_hash = self._get_file_hash(pdf_path)
        filename = Path(pdf_path).name
        
        db = await get_db_connection()
        
        # Verificar se já foi processado
        existing = await db.fetchval(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE file_hash = $1",
            file_hash
        )
        
        if existing > 0:
            logger.info(f"PDF {filename} já foi processado ({existing} chunks)")
            return {
                "file": filename,
                "status": "already_processed",
                "chunks": existing
            }
        
        # Processar chunks em BATCH para performance
        logger.info(f"Processando {len(chunks)} chunks em batches de {BATCH_SIZE}...")
        
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i:i + BATCH_SIZE]
            
            try:
                # Gerar embeddings em batch (uma chamada para múltiplos textos)
                embeddings = await self._get_embeddings_batch(batch)
                
                # Salvar no banco
                for j, (chunk, embedding) in enumerate(zip(batch, embeddings)):
                    await db.execute("""
                        INSERT INTO knowledge_chunks 
                        (content, embedding, file_name, file_hash, chunk_index)
                        VALUES ($1, $2, $3, $4, $5)
                    """, chunk, embedding, filename, file_hash, i + j)
                    saved += 1
                
                logger.info(f"Processados {saved}/{len(chunks)} chunks")
                    
            except Exception as e:
                logger.error(f"Erro no batch {i}-{i+BATCH_SIZE}: {e}")
                continue
        
        logger.info(f"Concluído: {saved} chunks salvos de {filename}")
        
        # Invalidar cache após nova ingestão
        await KnowledgeCache.invalidate_on_ingest()
        
        return {
            "file": filename,
            "status": "success",
            "total_chunks": len(chunks),
            "saved_chunks": saved
        }
    
    async def ingest_all_pdfs(self, folder_path: str = "knowledge") -> List[dict]:
        """Processa todos os PDFs de uma pasta"""
        results = []
        folder = Path(folder_path)
        
        if not folder.exists():
            return [{"error": f"Pasta {folder_path} não encontrada"}]
        
        pdf_files = list(folder.glob("*.pdf"))
        logger.info(f"Encontrados {len(pdf_files)} PDFs para processar")
        
        for pdf_path in pdf_files:
            result = await self.ingest_pdf(str(pdf_path))
            results.append(result)
        
        return results
    
    # ==================== BUSCA ====================
    
    async def search(self, query: str, top_k: int = 5) -> List[dict]:
        """
        Busca os chunks mais relevantes para uma query.
        Retorna lista de chunks com score de similaridade.
        
        Usa cache de embeddings e cache de resultados.
        """
        # Verificar cache de RESULTADO primeiro
        cached_result = await KnowledgeCache.get("vector_search", query, top_k=top_k)
        if cached_result is not None:
            logger.info(f"Busca vetorial retornada do CACHE: {query[:50]}...")
            return cached_result
        
        # Gerar embedding da query (com cache de embedding)
        query_embedding = await self._get_embedding_cached(query)
        
        db = await get_db_connection()
        
        # Busca por similaridade usando pgvector + HNSW index
        results = await db.fetch("""
            SELECT 
                content,
                file_name,
                chunk_index,
                1 - (embedding <=> $1::vector) as similarity
            FROM knowledge_chunks
            ORDER BY embedding <=> $1::vector
            LIMIT $2
        """, query_embedding, top_k)
        
        result = [
            {
                "content": r["content"],
                "file": r["file_name"],
                "chunk": r["chunk_index"],
                "similarity": float(r["similarity"])
            }
            for r in results
        ]
        
        # Cachear resultado
        await KnowledgeCache.set("vector_search", query, result, top_k=top_k)
        
        return result
    
    async def search_batch(self, queries: List[str], top_k: int = 5) -> Dict[str, List[dict]]:
        """
        Busca em BATCH - múltiplas queries em paralelo.
        
        Muito mais eficiente do que múltiplas chamadas sequenciais.
        
        Args:
            queries: Lista de queries
            top_k: Número de resultados por query
            
        Returns:
            Dict mapeando query -> resultados
        """
        logger.info(f"Busca em batch: {len(queries)} queries")
        
        # Criar tasks para execução paralela
        async def search_single(query: str):
            return query, await self.search(query, top_k)
        
        # Limitar concorrência
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_BATCHES)
        
        async def bounded_search(query: str):
            async with semaphore:
                return await search_single(query)
        
        # Executar todas em paralelo (com limite)
        tasks = [bounded_search(q) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Montar resultado
        result_dict = {}
        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"Erro em busca batch: {r}")
            else:
                query, search_results = r
                result_dict[query] = search_results
        
        logger.info(f"Batch concluído: {len(result_dict)}/{len(queries)} queries bem-sucedidas")
        return result_dict
    
    async def get_context_for_query(self, query: str, max_tokens: int = 2000) -> str:
        """
        Retorna contexto relevante formatado para usar no prompt.
        Limita pelo número de tokens.
        """
        results = await self.search(query, top_k=10)
        
        context_parts = []
        total_tokens = 0
        
        for r in results:
            chunk_tokens = len(self.tokenizer.encode(r["content"]))
            
            if total_tokens + chunk_tokens > max_tokens:
                break
            
            context_parts.append(r["content"])
            total_tokens += chunk_tokens
        
        if not context_parts:
            return ""
        
        return "\n\n---\n\n".join(context_parts)
    
    # ==================== EMBEDDINGS ====================
    
    async def _get_embedding_cached(self, text: str) -> str:
        """
        Gera embedding com cache.
        Evita recalcular embeddings para textos repetidos.
        """
        # Verificar cache primeiro
        cached = await EmbeddingCache.get(text)
        if cached:
            return cached
        
        # Gerar embedding
        embedding = await self._get_embedding(text)
        
        # Cachear
        await EmbeddingCache.set(text, embedding)
        
        return embedding
    
    async def _get_embedding(self, text: str) -> str:
        """Gera embedding usando OpenAI (sem cache)"""
        response = self.client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text
        )
        
        # Converter para formato pgvector
        embedding = response.data[0].embedding
        return f"[{','.join(map(str, embedding))}]"
    
    async def _get_embeddings_batch(self, texts: List[str]) -> List[str]:
        """
        Gera embeddings em batch (uma chamada para múltiplos textos).
        Muito mais eficiente que chamadas individuais.
        
        Também verifica cache individual para cada texto.
        """
        embeddings = []
        texts_to_compute = []
        cached_indices = {}
        
        # Verificar cache para cada texto
        for i, text in enumerate(texts):
            cached = await EmbeddingCache.get(text)
            if cached:
                cached_indices[i] = cached
            else:
                texts_to_compute.append((i, text))
        
        # Se todos estão em cache, retornar
        if not texts_to_compute:
            logger.debug(f"Batch de {len(texts)} embeddings: 100% do cache")
            return [cached_indices[i] for i in range(len(texts))]
        
        # Calcular os que faltam em uma única chamada
        try:
            compute_texts = [t[1] for t in texts_to_compute]
            
            response = self.client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=compute_texts
            )
            
            # Mapear resultados
            computed = {}
            for j, data in enumerate(response.data):
                orig_index = texts_to_compute[j][0]
                orig_text = texts_to_compute[j][1]
                embedding_str = f"[{','.join(map(str, data.embedding))}]"
                computed[orig_index] = embedding_str
                
                # Cachear para próximas vezes
                await EmbeddingCache.set(orig_text, embedding_str)
            
            # Montar resultado final na ordem correta
            for i in range(len(texts)):
                if i in cached_indices:
                    embeddings.append(cached_indices[i])
                else:
                    embeddings.append(computed[i])
            
            logger.debug(f"Batch de {len(texts)} embeddings: {len(cached_indices)} cache, {len(texts_to_compute)} computados")
            
        except Exception as e:
            logger.error(f"Erro ao gerar embeddings em batch: {e}")
            # Fallback para chamadas individuais
            for i, text in enumerate(texts):
                if i in cached_indices:
                    embeddings.append(cached_indices[i])
                else:
                    emb = await self._get_embedding(text)
                    embeddings.append(emb)
        
        return embeddings
    
    # ==================== HELPERS ====================
    
    def _extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extrai texto de um PDF"""
        try:
            reader = PdfReader(pdf_path)
            text_parts = []
            
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            
            return "\n\n".join(text_parts)
        except Exception as e:
            logger.error(f"Erro ao extrair PDF {pdf_path}: {e}")
            return ""
    
    def _create_chunks(self, text: str) -> List[str]:
        """Divide texto em chunks com overlap"""
        tokens = self.tokenizer.encode(text)
        chunks = []
        
        start = 0
        while start < len(tokens):
            end = start + CHUNK_SIZE
            chunk_tokens = tokens[start:end]
            chunk_text = self.tokenizer.decode(chunk_tokens)
            
            # Limpar chunk
            chunk_text = chunk_text.strip()
            if chunk_text:
                chunks.append(chunk_text)
            
            start = end - CHUNK_OVERLAP
        
        return chunks
    
    def _get_file_hash(self, file_path: str) -> str:
        """Gera hash do arquivo para evitar duplicação"""
        with open(file_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    
    # ==================== ESTATÍSTICAS ====================
    
    async def get_stats(self) -> dict:
        """Retorna estatísticas da base de conhecimento"""
        db = await get_db_connection()
        
        total_chunks = await db.fetchval("SELECT COUNT(*) FROM knowledge_chunks")
        
        files = await db.fetch("""
            SELECT file_name, COUNT(*) as chunks
            FROM knowledge_chunks
            GROUP BY file_name
            ORDER BY file_name
        """)
        
        return {
            "total_chunks": total_chunks,
            "files": [{"name": f["file_name"], "chunks": f["chunks"]} for f in files]
        }


# Instância global
knowledge_service = KnowledgeService()
