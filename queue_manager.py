"""
Sistema de Filas com Concorrência Otimizada
Usa locks globais por canal para evitar travamentos
"""
import asyncio
from typing import List, Dict, Set
from dataclasses import dataclass, field
import discord

@dataclass
class FilaCanal:
    """Representa a fila de um canal com ambos os tipos"""
    canal_id: int
    valores: Dict[str, Dict[str, List[discord.Member]]] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

class QueueManager:
    """
    Gerenciador de filas thread-safe com locks globais.
    Cada canal tem UM único lock, evitando contenção excessiva.
    """
    
    def __init__(self):
        self.filas: Dict[int, FilaCanal] = {}
        self._global_lock = asyncio.Lock()  # Para operações estruturais
    
    def inicializar_canal(self, canal_id: int, valores: List[str]):
        """Cria estrutura de fila para um novo canal"""
        self.filas[canal_id] = FilaCanal(
            canal_id=canal_id,
            valores={
                valor: {"normal": [], "fullump": []}
                for valor in valores
            }
        )
    
    async def _obter_lock(self, canal_id: int) -> asyncio.Lock:
        """Obtém o lock do canal, criando se necessário"""
        if canal_id not in self.filas:
            async with self._global_lock:
                if canal_id not in self.filas:
                    # Inicializar com valores vazios
                    self.filas[canal_id] = FilaCanal(canal_id=canal_id)
        
        return self.filas[canal_id].lock
    
    async def entrar_fila(
        self, 
        canal_id: int, 
        valor: str, 
        tipo: str, 
        usuario: discord.Member
    ) -> tuple[bool, str]:
        """
        Adiciona usuário à fila de forma thread-safe.
        Retorna (sucesso, mensagem)
        """
        lock = await self._obter_lock(canal_id)
        
        async with lock:
            fila_canal = self.filas[canal_id]
            
            # Verificar se já está em outra fila deste canal
            for v, tipos in fila_canal.valores.items():
                for sel, lista in tipos.items():
                    if usuario in lista:
                        return False, f"❌ Já está na fila de R$ {v} ({sel})"
            
            # Adicionar à fila
            if valor not in fila_canal.valores:
                fila_canal.valores[valor] = {"normal": [], "fullump": []}
            
            fila_canal.valores[valor][tipo].append(usuario)
            return True, f"✅ Entrou na fila de R$ {valor} ({tipo})"
    
    async def sair_fila(
        self, 
        canal_id: int, 
        usuario: discord.Member
    ) -> tuple[bool, str]:
        """Remove usuário de qualquer fila deste canal"""
        lock = await self._obter_lock(canal_id)
        
        async with lock:
            fila_canal = self.filas[canal_id]
            
            for valor, tipos in fila_canal.valores.items():
                for tipo, lista in tipos.items():
                    if usuario in lista:
                        lista.remove(usuario)
                        return True, f"👋 Saiu da fila de R$ {valor} ({tipo})"
            
            return False, "❌ Não está em nenhuma fila"
    
    async def obter_fila(self, canal_id: int, valor: str) -> Dict[str, List[discord.Member]]:
        """Retorna snapshot da fila (cópia segura)"""
        lock = await self._obter_lock(canal_id)
        
        async with lock:
            fila_canal = self.filas[canal_id]
            if valor not in fila_canal.valores:
                return {"normal": [], "fullump": []}
            
            # Retorna cópia para evitar modificação externa
            return {
                "normal": fila_canal.valores[valor]["normal"].copy(),
                "fullump": fila_canal.valores[valor]["fullump"].copy()
            }
    
    async def remover_usuarios(
        self, 
        canal_id: int, 
        valor: str, 
        tipo: str, 
        quantidade: int
    ) -> List[discord.Member]:
        """Remove N primeiros usuários da fila e retorna"""
        lock = await self._obter_lock(canal_id)
        
        async with lock:
            fila_canal = self.filas[canal_id]
            if valor not in fila_canal.valores:
                return []
            
            lista = fila_canal.valores[valor][tipo]
            removidos = lista[:quantidade]
            del lista[:quantidade]
            return removidos
    
    async def limpar_canal(self, canal_id: int):
        """Limpa todas as filas de um canal"""
        lock = await self._obter_lock(canal_id)
        
        async with lock:
            if canal_id in self.filas:
                fila_canal = self.filas[canal_id]
                for valor in fila_canal.valores:
                    fila_canal.valores[valor]["normal"].clear()
                    fila_canal.valores[valor]["fullump"].clear()
    
    async def obter_stats_canal(self, canal_id: int) -> dict:
        """Retorna estatísticas do canal"""
        lock = await self._obter_lock(canal_id)
        
        async with lock:
            if canal_id not in self.filas:
                return {"total_usuarios": 0, "valores": {}}
            
            fila_canal = self.filas[canal_id]
            stats = {"total_usuarios": 0, "valores": {}}
            
            for valor, tipos in fila_canal.valores.items():
                normal = len(tipos["normal"])
                fullump = len(tipos["fullump"])
                stats["valores"][valor] = {
                    "normal": normal,
                    "fullump": fullump,
                    "total": normal + fullump
                }
                stats["total_usuarios"] += normal + fullump
            
            return stats
    
    async def limpar_tudo(self):
        """Limpa todas as filas de todos os canais"""
        async with self._global_lock:
            for canal_id in self.filas:
                await self.limpar_canal(canal_id)


# Instância global
queue_manager = QueueManager()
