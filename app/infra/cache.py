"""
Sistema de Cache para RAG (Knowledge Retrieval)
===============================================

Cache inteligente para queries de conhecimento usando Redis.
Reduz latência e custos de inferência para queries repetidas.

Estratégias:
- Cache de contexto por query hash
- Cache de EMBEDDINGS de query (evita recalcular)
- TTL configurável por tipo de cache
- Invalidação automática quando base é atualizada
- Métricas de hit/miss
- Pré-aquecimento de cache no startup
"""
import os
import json
import hashlib
import logging
import asyncio
from typing import Optional, Any, Dict, List
from datetime import timedelta
from functools import wraps

from app.infra.redis import get_redis_client

logger = logging.getLogger(__name__)


# Configurações de TTL (em segundos)
CACHE_TTL = {
    "vector_search": int(os.getenv("CACHE_TTL_VECTOR", 3600)),           # 1 hora
    "structural_navigation": int(os.getenv("CACHE_TTL_STRUCTURAL", 1800)),  # 30 min
    "context": int(os.getenv("CACHE_TTL_CONTEXT", 3600)),                # 1 hora
    "toc": int(os.getenv("CACHE_TTL_TOC", 86400)),                       # 24 horas
    "document_tree": int(os.getenv("CACHE_TTL_TREE", 86400)),            # 24 horas
    "embedding": int(os.getenv("CACHE_TTL_EMBEDDING", 604800)),          # 7 dias (embeddings são estáveis)
}

# Prefixos de chave
CACHE_PREFIX = "quickvet:cache:"
METRICS_PREFIX = "quickvet:metrics:"
EMBEDDING_PREFIX = "quickvet:embedding:"
WARMUP_PREFIX = "quickvet:warmup:"

# Queries frequentes para pré-aquecimento
WARMUP_QUERIES = [
    # Emergências
    "meu cachorro está vomitando",
    "cachorro com diarreia",
    "gato não come",
    "animal envenenado",
    "cachorro atropelado",
    "gato caiu da janela",
    # Doenças comuns
    "cinomose",
    "parvovirose",
    "leptospirose",
    "erliquiose",
    "giárdia",
    "verminose",
    # Cuidados básicos
    "vacinas cachorro",
    "vacinas gato",
    "vermífugo",
    "alimentação filhote",
    "castração",
    # Sintomas
    "coceira intensa",
    "queda de pelo",
    "tosse",
    "febre",
    "sangue nas fezes",
    "sangue na urina",
]


class CacheMetrics:
    """Métricas de uso do cache"""
    
    @staticmethod
    async def record_hit(cache_type: str):
        """Registra um cache hit"""
        try:
            redis = get_redis_client()
            await redis.hincrby(f"{METRICS_PREFIX}cache", f"{cache_type}:hits", 1)
        except:
            pass
    
    @staticmethod
    async def record_miss(cache_type: str):
        """Registra um cache miss"""
        try:
            redis = get_redis_client()
            await redis.hincrby(f"{METRICS_PREFIX}cache", f"{cache_type}:misses", 1)
        except:
            pass
    
    @staticmethod
    async def get_stats() -> Dict[str, Any]:
        """Retorna estatísticas do cache"""
        try:
            redis = get_redis_client()
            stats = await redis.hgetall(f"{METRICS_PREFIX}cache")
            
            result = {}
            for key, value in stats.items():
                parts = key.split(":")
                if len(parts) == 2:
                    cache_type, metric = parts
                    if cache_type not in result:
                        result[cache_type] = {}
                    result[cache_type][metric] = int(value)
            
            # Calcular hit rate
            for cache_type, metrics in result.items():
                hits = metrics.get("hits", 0)
                misses = metrics.get("misses", 0)
                total = hits + misses
                if total > 0:
                    result[cache_type]["hit_rate"] = round(hits / total * 100, 2)
            
            # Adicionar estatísticas de embedding
            embedding_count = 0
            async for _ in redis.scan_iter(match=f"{EMBEDDING_PREFIX}*"):
                embedding_count += 1
            result["embeddings_cached"] = embedding_count
            
            return result
        except Exception as e:
            logger.warning(f"Erro ao obter métricas de cache: {e}")
            return {}


class EmbeddingCache:
    """
    Cache de embeddings de query.
    Evita recalcular embeddings para queries repetidas ou similares.
    
    Como embeddings são determinísticos e estáveis, podem ter TTL longo.
    """
    
    @staticmethod
    def _get_key(text: str) -> str:
        """Gera chave de cache para embedding"""
        # Normalizar texto
        normalized = text.lower().strip()
        hash_key = hashlib.sha256(normalized.encode()).hexdigest()[:32]
        return f"{EMBEDDING_PREFIX}{hash_key}"
    
    @staticmethod
    async def get(text: str) -> Optional[str]:
        """
        Busca embedding no cache.
        
        Returns:
            String do embedding no formato pgvector ou None
        """
        try:
            redis = get_redis_client()
            key = EmbeddingCache._get_key(text)
            
            cached = await redis.get(key)
            
            if cached:
                await CacheMetrics.record_hit("embedding")
                logger.debug(f"Embedding CACHE HIT: {text[:30]}...")
                return cached
            
            await CacheMetrics.record_miss("embedding")
            return None
            
        except Exception as e:
            logger.warning(f"Erro ao buscar embedding no cache: {e}")
            return None
    
    @staticmethod
    async def set(text: str, embedding: str, ttl: Optional[int] = None):
        """
        Armazena embedding no cache.
        
        Args:
            text: Texto original
            embedding: String do embedding no formato pgvector
            ttl: TTL em segundos (padrão: 7 dias)
        """
        try:
            redis = get_redis_client()
            key = EmbeddingCache._get_key(text)
            
            if ttl is None:
                ttl = CACHE_TTL["embedding"]
            
            await redis.setex(key, ttl, embedding)
            logger.debug(f"Embedding CACHED: {text[:30]}... (TTL: {ttl}s)")
            
        except Exception as e:
            logger.warning(f"Erro ao salvar embedding no cache: {e}")
    
    @staticmethod
    async def get_or_compute(text: str, compute_func) -> str:
        """
        Busca embedding no cache ou computa se não existir.
        
        Args:
            text: Texto para embedding
            compute_func: Função assíncrona que gera o embedding
            
        Returns:
            String do embedding no formato pgvector
        """
        cached = await EmbeddingCache.get(text)
        if cached:
            return cached
        
        # Computar embedding
        embedding = await compute_func(text)
        
        # Cachear
        await EmbeddingCache.set(text, embedding)
        
        return embedding


class KnowledgeCache:
    """Cache para sistema de conhecimento RAG"""
    
    @staticmethod
    def _generate_key(prefix: str, query: str, **params) -> str:
        """Gera chave de cache baseada na query e parâmetros"""
        # Normalizar query
        normalized = query.lower().strip()
        
        # Incluir parâmetros na chave
        param_str = json.dumps(params, sort_keys=True) if params else ""
        
        # Hash para evitar chaves muito longas
        content = f"{normalized}:{param_str}"
        hash_key = hashlib.sha256(content.encode()).hexdigest()[:16]
        
        return f"{CACHE_PREFIX}{prefix}:{hash_key}"
    
    @staticmethod
    async def get(cache_type: str, query: str, **params) -> Optional[Any]:
        """
        Busca valor no cache.
        
        Args:
            cache_type: Tipo do cache (vector_search, structural_navigation, etc)
            query: Query de busca
            **params: Parâmetros adicionais (top_k, max_steps, etc)
            
        Returns:
            Valor cacheado ou None se não encontrado
        """
        try:
            redis = get_redis_client()
            key = KnowledgeCache._generate_key(cache_type, query, **params)
            
            cached = await redis.get(key)
            
            if cached:
                await CacheMetrics.record_hit(cache_type)
                logger.debug(f"Cache HIT: {cache_type} - {query[:50]}...")
                return json.loads(cached)
            
            await CacheMetrics.record_miss(cache_type)
            logger.debug(f"Cache MISS: {cache_type} - {query[:50]}...")
            return None
            
        except Exception as e:
            logger.warning(f"Erro ao buscar cache: {e}")
            return None
    
    @staticmethod
    async def set(cache_type: str, query: str, value: Any, ttl: Optional[int] = None, **params):
        """
        Armazena valor no cache.
        
        Args:
            cache_type: Tipo do cache
            query: Query de busca
            value: Valor a ser cacheado
            ttl: TTL em segundos (usa padrão se não especificado)
            **params: Parâmetros adicionais
        """
        try:
            redis = get_redis_client()
            key = KnowledgeCache._generate_key(cache_type, query, **params)
            
            # Usar TTL padrão se não especificado
            if ttl is None:
                ttl = CACHE_TTL.get(cache_type, 3600)
            
            await redis.setex(key, ttl, json.dumps(value))
            logger.debug(f"Cache SET: {cache_type} - {query[:50]}... (TTL: {ttl}s)")
            
        except Exception as e:
            logger.warning(f"Erro ao salvar cache: {e}")
    
    @staticmethod
    async def invalidate(cache_type: str = None, query: str = None, **params):
        """
        Invalida cache.
        
        Args:
            cache_type: Tipo específico (None = todos)
            query: Query específica (None = todas do tipo)
            **params: Parâmetros da query
        """
        try:
            redis = get_redis_client()
            
            if query and cache_type:
                # Invalidar query específica
                key = KnowledgeCache._generate_key(cache_type, query, **params)
                await redis.delete(key)
                logger.info(f"Cache invalidado: {key}")
            
            elif cache_type:
                # Invalidar todo o tipo
                pattern = f"{CACHE_PREFIX}{cache_type}:*"
                keys = []
                async for key in redis.scan_iter(match=pattern):
                    keys.append(key)
                
                if keys:
                    await redis.delete(*keys)
                    logger.info(f"Cache invalidado: {len(keys)} chaves de {cache_type}")
            
            else:
                # Invalidar tudo
                pattern = f"{CACHE_PREFIX}*"
                keys = []
                async for key in redis.scan_iter(match=pattern):
                    keys.append(key)
                
                if keys:
                    await redis.delete(*keys)
                    logger.info(f"Cache invalidado: {len(keys)} chaves total")
                    
        except Exception as e:
            logger.warning(f"Erro ao invalidar cache: {e}")
    
    @staticmethod
    async def invalidate_on_ingest():
        """
        Invalida cache quando novos documentos são ingeridos.
        Chamado após ingestão de PDFs.
        """
        await KnowledgeCache.invalidate()  # Invalidar tudo
        logger.info("Cache invalidado após ingestão de documentos")


class CacheWarmer:
    """
    Pré-aquecimento de cache no startup.
    Carrega queries frequentes para reduzir latência inicial.
    """
    
    @staticmethod
    async def warmup(search_func, queries: List[str] = None):
        """
        Pré-aquece o cache com queries frequentes.
        
        Args:
            search_func: Função de busca async (knowledge_service.search)
            queries: Lista de queries (usa padrão se não especificado)
        """
        if queries is None:
            queries = WARMUP_QUERIES
        
        logger.info(f"Iniciando pré-aquecimento de cache com {len(queries)} queries...")
        
        # Processar em batches para não sobrecarregar
        batch_size = 5
        total_warmed = 0
        
        for i in range(0, len(queries), batch_size):
            batch = queries[i:i + batch_size]
            
            # Executar batch em paralelo
            tasks = [search_func(q) for q in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for j, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"Warmup falhou para '{batch[j]}': {result}")
                else:
                    total_warmed += 1
            
            # Pequena pausa entre batches
            await asyncio.sleep(0.5)
        
        logger.info(f"Pré-aquecimento concluído: {total_warmed}/{len(queries)} queries cacheadas")
        
        # Registrar timestamp do warmup
        try:
            redis = get_redis_client()
            import datetime
            await redis.set(f"{WARMUP_PREFIX}last_run", datetime.datetime.now().isoformat())
            await redis.set(f"{WARMUP_PREFIX}queries_warmed", str(total_warmed))
        except:
            pass
        
        return total_warmed
    
    @staticmethod
    async def get_warmup_status() -> Dict[str, Any]:
        """Retorna status do último warmup"""
        try:
            redis = get_redis_client()
            last_run = await redis.get(f"{WARMUP_PREFIX}last_run")
            queries_warmed = await redis.get(f"{WARMUP_PREFIX}queries_warmed")
            
            return {
                "last_run": last_run or "never",
                "queries_warmed": int(queries_warmed) if queries_warmed else 0,
                "warmup_queries_total": len(WARMUP_QUERIES)
            }
        except Exception as e:
            return {"error": str(e)}


def cached(cache_type: str, ttl: Optional[int] = None):
    """
    Decorator para cachear resultado de funções async.
    
    Usage:
        @cached("vector_search")
        async def search(query: str, top_k: int = 5):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extrair query dos argumentos
            query = kwargs.get("query") or (args[1] if len(args) > 1 else None)
            
            if not query:
                return await func(*args, **kwargs)
            
            # Tentar buscar do cache
            cache_params = {k: v for k, v in kwargs.items() if k != "query"}
            cached_result = await KnowledgeCache.get(cache_type, query, **cache_params)
            
            if cached_result is not None:
                return cached_result
            
            # Executar função e cachear
            result = await func(*args, **kwargs)
            
            if result:
                await KnowledgeCache.set(cache_type, query, result, ttl, **cache_params)
            
            return result
        
        return wrapper
    return decorator
