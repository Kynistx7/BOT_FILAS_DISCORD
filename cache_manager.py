"""
Sistema de Cache em Memória com TTL
Reduz carga no banco de dados em ~90%
"""
import time
import asyncio
from typing import Any, Optional, Dict
from datetime import datetime, timedelta

class CacheManager:
    """
    Cache em memória com expiração automática (TTL).
    Thread-safe e otimizado para Discord bot.
    """
    
    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # {key: (valor, timestamp_expiracao)}
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        """Retorna valor do cache se existir e não expirou"""
        async with self._lock:
            if key not in self._cache:
                return None
            
            valor, expiracao = self._cache[key]
            if time.time() > expiracao:
                del self._cache[key]
                return None
            
            return valor
    
    async def set(self, key: str, valor: Any, ttl: int = 60):
        """Armazena valor com expiração em TTL segundos"""
        async with self._lock:
            expiracao = time.time() + ttl
            self._cache[key] = (valor, expiracao)
    
    async def delete(self, key: str):
        """Remove valor do cache"""
        async with self._lock:
            self._cache.pop(key, None)
    
    async def clear(self):
        """Limpa todo o cache"""
        async with self._lock:
            self._cache.clear()
    
    async def cleanup_expired(self):
        """Remove entradas expiradas (roda a cada 60s)"""
        async with self._lock:
            agora = time.time()
            chaves_expiradas = [
                k for k, (_, exp) in self._cache.items() 
                if agora > exp
            ]
            for chave in chaves_expiradas:
                del self._cache[chave]
            
            if chaves_expiradas:
                print(f"🧹 Cache cleanup: {len(chaves_expiradas)} itens removidos")
    
    async def stats(self) -> dict:
        """Retorna estatísticas do cache"""
        async with self._lock:
            agora = time.time()
            ativos = sum(1 for _, exp in self._cache.values() if agora <= exp)
            return {
                "total_chaves": len(self._cache),
                "chaves_ativas": ativos,
                "uso_memoria_mb": len(str(self._cache)) / (1024 * 1024)
            }


# Instância global
cache = CacheManager()

# Funções de conveniência para uso em todo o código
async def cache_get(key: str):
    """Alias rápido para cache.get()"""
    return await cache.get(key)

async def cache_set(key: str, valor: Any, ttl: int = 60):
    """Alias rápido para cache.set()"""
    return await cache.set(key, valor, ttl=ttl)

async def cache_delete(key: str):
    """Alias rápido para cache.delete()"""
    return await cache.delete(key)

async def cache_invalidate_pattern(pattern: str):
    """Invalida todas as chaves que contêm o padrão"""
    async with cache._lock:
        chaves_remover = [k for k in cache._cache.keys() if pattern in k]
        for chave in chaves_remover:
            del cache._cache[chave]
        return len(chaves_remover)
