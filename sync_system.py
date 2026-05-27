"""
Sistema de Sincronização por Eventos (ao invés de polling)
Substitui o loop de 5s por notificações em tempo real
"""
import asyncio
from typing import Callable, List
from datetime import datetime, timedelta
from collections import defaultdict

class EventBus:
    """
    Bus de eventos para sincronizar web-bot sem polling
    Permite subscrição a eventos específicos
    """
    
    def __init__(self):
        self._subscribers: dict[str, List[Callable]] = defaultdict(list)
        self._lock = asyncio.Lock()
    
    async def subscribe(self, evento: str, callback: Callable):
        """Se inscreve em um tipo de evento"""
        async with self._lock:
            self._subscribers[evento].append(callback)
    
    async def unsubscribe(self, evento: str, callback: Callable):
        """Desinscreve de um tipo de evento"""
        async with self._lock:
            if evento in self._subscribers:
                self._subscribers[evento].remove(callback)
    
    async def emit(self, evento: str, dados: dict = None):
        """Dispara um evento para todos os inscritos"""
        if evento not in self._subscribers:
            return
        
        callbacks = self._subscribers[evento].copy()
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(dados or {})
                else:
                    callback(dados or {})
            except Exception as e:
                print(f"❌ Erro em callback para evento {evento}: {e}")

class CircuitBreaker:
    """
    Proteção contra canais/serviços que travam
    Padrão: Falha -> Abre -> Testa -> Reconecta
    """
    
    def __init__(self, limite_falhas: int = 5, timeout_reset: int = 60):
        self.limite_falhas = limite_falhas
        self.timeout_reset = timeout_reset
        self._falhas: dict[str, int] = defaultdict(int)
        self._timeout_em: dict[str, datetime] = {}
        self._lock = asyncio.Lock()
    
    async def registrar_sucesso(self, chave: str):
        """Reseta contador ao sucesso"""
        async with self._lock:
            self._falhas[chave] = 0
            self._timeout_em.pop(chave, None)
    
    async def registrar_falha(self, chave: str) -> bool:
        """Registra falha. Retorna True se está aberto (circuit breaker ativado)"""
        async with self._lock:
            self._falhas[chave] += 1
            
            if self._falhas[chave] >= self.limite_falhas:
                self._timeout_em[chave] = datetime.now() + timedelta(seconds=self.timeout_reset)
                print(f"🚨 CIRCUIT BREAKER ABERTO para {chave} por {self.timeout_reset}s")
                return True
            
            return False
    
    async def pode_usar(self, chave: str) -> bool:
        """Verifica se o serviço pode ser usado"""
        async with self._lock:
            if chave not in self._timeout_em:
                return True
            
            # Se timeout expirou, tenta reconectar (meia-aberta)
            if datetime.now() > self._timeout_em[chave]:
                print(f"🔄 Tentando reconectar {chave}...")
                self._falhas[chave] = 0
                del self._timeout_em[chave]
                return True
            
            return False
    
    async def status(self, chave: str) -> str:
        """Retorna status do circuit breaker"""
        async with self._lock:
            if chave in self._timeout_em:
                tempo_restante = (self._timeout_em[chave] - datetime.now()).total_seconds()
                return f"🔴 ABERTO ({int(tempo_restante)}s)"
            
            falhas = self._falhas[chave]
            if falhas == 0:
                return "🟢 FECHADO"
            else:
                return f"🟡 SEMI-ABERTO ({falhas}/{self.limite_falhas})"

class CanaisMonitor:
    """
    Monitora saúde de todos os canais Discord
    Permite identificar quais estão travando
    """
    
    def __init__(self):
        self.circuit_breaker = CircuitBreaker(limite_falhas=5, timeout_reset=60)
        self._stats: dict[int, dict] = {}
        self._lock = asyncio.Lock()
    
    async def registrar_operacao(self, canal_id: int, sucesso: bool, tempo_ms: float = 0):
        """Registra resultado de operação em um canal"""
        chave = f"canal_{canal_id}"
        
        if sucesso:
            await self.circuit_breaker.registrar_sucesso(chave)
        else:
            abriu = await self.circuit_breaker.registrar_falha(chave)
            if abriu:
                print(f"⚠️ Canal {canal_id} foi isolado após muitas falhas")
        
        async with self._lock:
            if canal_id not in self._stats:
                self._stats[canal_id] = {
                    "total_ops": 0,
                    "sucessos": 0,
                    "falhas": 0,
                    "tempo_medio_ms": 0,
                    "ultima_operacao": datetime.now()
                }
            
            stats = self._stats[canal_id]
            stats["total_ops"] += 1
            if sucesso:
                stats["sucessos"] += 1
                stats["tempo_medio_ms"] = (
                    stats["tempo_medio_ms"] * (stats["sucessos"] - 1) + tempo_ms
                ) / stats["sucessos"]
            else:
                stats["falhas"] += 1
            stats["ultima_operacao"] = datetime.now()
    
    async def pode_usar_canal(self, canal_id: int) -> bool:
        """Verifica se o canal pode ser usado"""
        chave = f"canal_{canal_id}"
        pode_usar = await self.circuit_breaker.pode_usar(chave)
        
        if not pode_usar:
            print(f"⛔ Canal {canal_id} está isolado (circuit breaker ativo)")
        
        return pode_usar
    
    async def obter_status_canais(self) -> dict:
        """Retorna status de todos os canais"""
        async with self._lock:
            resultado = {}
            for canal_id, stats in self._stats.items():
                chave = f"canal_{canal_id}"
                status_cb = await self.circuit_breaker.status(chave)
                
                taxa_sucesso = (
                    (stats["sucessos"] / stats["total_ops"] * 100)
                    if stats["total_ops"] > 0 else 0
                )
                
                resultado[canal_id] = {
                    "status_circuit_breaker": status_cb,
                    "total_operacoes": stats["total_ops"],
                    "taxa_sucesso_pct": round(taxa_sucesso, 1),
                    "tempo_medio_ms": round(stats["tempo_medio_ms"], 2),
                    "ultima_operacao": stats["ultima_operacao"].isoformat()
                }
            
            return resultado
    
    async def resetar_stats(self, canal_id: int = None):
        """Reseta estatísticas"""
        async with self._lock:
            if canal_id:
                self._stats.pop(canal_id, None)
            else:
                self._stats.clear()
            print("🧹 Stats resetadas")

# ==========================================
# INSTÂNCIAS GLOBAIS
# ==========================================
event_bus = EventBus()
canais_monitor = CanaisMonitor()

# ==========================================
# EVENTOS PADRÃO
# ==========================================
EVENTO_PARTIDA_CRIADA = "partida.criada"
EVENTO_PARTIDA_CANCELADA = "partida.cancelada"
EVENTO_PARTIDA_FINALIZADA = "partida.finalizada"
EVENTO_JOGADOR_ENTROU_FILA = "jogador.entrou_fila"
EVENTO_JOGADOR_SAIU_FILA = "jogador.saiu_fila"
EVENTO_STATUS_ATUALIZADO = "status.atualizado"
EVENTO_CANAL_ISOLADO = "canal.isolado"
