#!/usr/bin/env python3
"""
Script de teste para validar a instalação do sistema otimizado
Execute: python test_sistema.py
"""

import asyncio
import sys
from datetime import datetime

# ============================================================
# CORES PARA TERMINAL
# ============================================================
class Cores:
    VERDE = '\033[92m'
    VERMELHO = '\033[91m'
    AMARELO = '\033[93m'
    AZUL = '\033[94m'
    RESET = '\033[0m'
    NEGRITO = '\033[1m'

def teste_ok(mensagem):
    print(f"{Cores.VERDE}✅ {mensagem}{Cores.RESET}")

def teste_erro(mensagem):
    print(f"{Cores.VERMELHO}❌ {mensagem}{Cores.RESET}")

def teste_aviso(mensagem):
    print(f"{Cores.AMARELO}⚠️  {mensagem}{Cores.RESET}")

def teste_info(mensagem):
    print(f"{Cores.AZUL}ℹ️  {mensagem}{Cores.RESET}")

# ============================================================
# TESTES
# ============================================================

async def testar_imports():
    """Testa se todos os módulos podem ser importados"""
    print(f"\n{Cores.NEGRITO}🧪 Testando Imports...{Cores.RESET}")
    
    modulos = {
        'cache_manager': 'from cache_manager import cache',
        'queue_manager': 'from queue_manager import queue_manager',
        'database_v2': 'from database_v2 import SessionLocal, PartidaDB, init_db',
        'db_operations': 'from db_operations import obter_stats_jogador',
        'sync_system': 'from sync_system import event_bus, canais_monitor'
    }
    
    erros = []
    for nome, import_str in modulos.items():
        try:
            exec(import_str)
            teste_ok(f"Módulo {nome}")
        except ImportError as e:
            teste_erro(f"Módulo {nome}: {e}")
            erros.append(nome)
        except Exception as e:
            teste_erro(f"Módulo {nome}: {type(e).__name__}: {e}")
            erros.append(nome)
    
    if erros:
        print(f"\n{Cores.AMARELO}Módulos com problemas: {', '.join(erros)}{Cores.RESET}")
        return False
    
    return True

async def testar_cache():
    """Testa funcionalidade do cache"""
    print(f"\n{Cores.NEGRITO}🧪 Testando Cache Manager...{Cores.RESET}")
    
    try:
        from cache_manager import cache
        
        # Test 1: Set e Get
        await cache.set("teste_key", "teste_valor", ttl=60)
        valor = await cache.get("teste_key")
        
        if valor == "teste_valor":
            teste_ok("Cache set/get básico")
        else:
            teste_erro("Cache retornou valor errado")
            return False
        
        # Test 2: Expiração
        await cache.set("expira", "x", ttl=1)
        await asyncio.sleep(1.1)
        valor_expirado = await cache.get("expira")
        
        if valor_expirado is None:
            teste_ok("Cache expiration")
        else:
            teste_erro("Cache não expirou corretamente")
            return False
        
        # Test 3: Stats
        stats = await cache.stats()
        teste_ok(f"Cache stats: {stats['chaves_ativas']} chaves ativas")
        
        return True
        
    except Exception as e:
        teste_erro(f"Erro no cache: {e}")
        return False

async def testar_queue_manager():
    """Testa funcionalidade do queue manager"""
    print(f"\n{Cores.NEGRITO}🧪 Testando Queue Manager...{Cores.RESET}")
    
    try:
        from queue_manager import queue_manager
        import discord
        from unittest.mock import Mock
        
        # Mock user
        user_mock = Mock(spec=discord.Member)
        user_mock.id = 123456
        user_mock.name = "TestUser"
        
        # Test 1: Inicializar canal
        queue_manager.inicializar_canal(999, ["1.00", "2.00"])
        teste_ok("Inicialização de canal")
        
        # Test 2: Entrar fila
        sucesso, msg = await queue_manager.entrar_fila(999, "1.00", "normal", user_mock)
        if sucesso:
            teste_ok("Usuário entrou na fila")
        else:
            teste_erro(f"Erro ao entrar: {msg}")
            return False
        
        # Test 3: Obter fila
        fila = await queue_manager.obter_fila(999, "1.00")
        if len(fila["normal"]) == 1:
            teste_ok("Fila retornou usuário corretamente")
        else:
            teste_erro("Fila com tamanho errado")
            return False
        
        # Test 4: Sair fila
        sucesso, msg = await queue_manager.sair_fila(999, user_mock)
        if sucesso:
            teste_ok("Usuário saiu da fila")
        else:
            teste_erro(f"Erro ao sair: {msg}")
            return False
        
        # Test 5: Stats
        await queue_manager.entrar_fila(999, "2.00", "normal", user_mock)
        stats = await queue_manager.obter_stats_canal(999)
        teste_ok(f"Stats canal: {stats['total_usuarios']} usuários")
        
        return True
        
    except Exception as e:
        teste_erro(f"Erro no queue manager: {e}")
        import traceback
        traceback.print_exc()
        return False

async def testar_database():
    """Testa database otimizado"""
    print(f"\n{Cores.NEGRITO}🧪 Testando Database...{Cores.RESET}")
    
    try:
        from database_v2 import init_db, SessionLocal, PartidaDB
        import os
        
        # Verificar se pode inicializar
        init_db()
        teste_ok("Database inicializado")
        
        # Tentar criar sessão
        db = SessionLocal()
        teste_ok("Sessão criada com sucesso")
        
        # Tentar query simples
        total = db.query(PartidaDB).count()
        teste_ok(f"Query bem-sucedida: {total} partidas no banco")
        
        db.close()
        
        # Verificar arquivo
        if os.path.exists("partidas.db"):
            tamanho_mb = os.path.getsize("partidas.db") / (1024 * 1024)
            teste_ok(f"Arquivo partidas.db: {tamanho_mb:.2f}MB")
        
        return True
        
    except Exception as e:
        teste_erro(f"Erro no database: {e}")
        import traceback
        traceback.print_exc()
        return False

async def testar_sync_system():
    """Testa sistema de sincronização"""
    print(f"\n{Cores.NEGRITO}🧪 Testando Sync System...{Cores.RESET}")
    
    try:
        from sync_system import event_bus, canais_monitor
        
        # Test 1: Event bus
        evento_recebido = False
        
        async def callback(dados):
            nonlocal evento_recebido
            evento_recebido = True
        
        await event_bus.subscribe("teste.evento", callback)
        await event_bus.emit("teste.evento", {"teste": "dados"})
        
        await asyncio.sleep(0.1)
        
        if evento_recebido:
            teste_ok("Event bus funcionando")
        else:
            teste_erro("Event bus não emitiu evento")
            return False
        
        # Test 2: Circuit breaker
        cb_pode_usar = await canais_monitor.pode_usar_canal(999)
        if cb_pode_usar:
            teste_ok("Circuit breaker permite canal novo")
        else:
            teste_erro("Circuit breaker bloqueou canal novo")
            return False
        
        # Test 3: Registrar operação
        await canais_monitor.registrar_operacao(999, sucesso=True, tempo_ms=50)
        status = await canais_monitor.obter_status_canais()
        if 999 in status:
            teste_ok(f"Monitor: {status[999]['status_circuit_breaker']}")
        
        return True
        
    except Exception as e:
        teste_erro(f"Erro no sync system: {e}")
        import traceback
        traceback.print_exc()
        return False

async def testar_db_operations():
    """Testa operações de banco com cache"""
    print(f"\n{Cores.NEGRITO}🧪 Testando DB Operations...{Cores.RESET}")
    
    try:
        from db_operations import obter_stats_jogador, obter_partidas_ativas_em_lote
        
        # Test 1: Obter stats (vai do cache depois do banco)
        stats1 = await obter_stats_jogador("123456")
        teste_ok(f"Stats jogador: {stats1['vitorias']} vitórias")
        
        # Test 2: Obter stats novamente (deve vir do cache)
        stats2 = await obter_stats_jogador("123456")
        if stats1 == stats2:
            teste_ok("Cache de stats funcionando")
        
        # Test 3: Obter partidas em lote
        partidas = await obter_partidas_ativas_em_lote()
        teste_ok(f"Partidas ativas: {len(partidas)}")
        
        return True
        
    except Exception as e:
        teste_erro(f"Erro nas db operations: {e}")
        import traceback
        traceback.print_exc()
        return False

async def teste_performance():
    """Testa performance do cache"""
    print(f"\n{Cores.NEGRITO}🧪 Testando Performance...{Cores.RESET}")
    
    try:
        from cache_manager import cache
        import time
        
        # Teste 1: Velocidade do cache
        inicio = time.time()
        for i in range(1000):
            await cache.set(f"perf_key_{i}", f"valor_{i}", ttl=60)
        tempo_set = time.time() - inicio
        teste_ok(f"1000 sets em cache: {tempo_set*1000:.0f}ms ({1000/tempo_set:.0f} ops/s)")
        
        # Teste 2: Velocidade de gets
        inicio = time.time()
        for i in range(1000):
            await cache.get(f"perf_key_{i}")
        tempo_get = time.time() - inicio
        teste_ok(f"1000 gets em cache: {tempo_get*1000:.0f}ms ({1000/tempo_get:.0f} ops/s)")
        
        return True
        
    except Exception as e:
        teste_erro(f"Erro no teste de performance: {e}")
        return False

# ============================================================
# MAIN
# ============================================================

async def main():
    print(f"\n{Cores.NEGRITO}{Cores.AZUL}")
    print("=" * 60)
    print("🧪 TESTE DO SISTEMA OTIMIZADO")
    print("=" * 60)
    print(f"{Cores.RESET}\n")
    print(f"Data/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Python: {sys.version.split()[0]}\n")
    
    resultados = []
    
    # Rodar testes
    resultados.append(("Imports", await testar_imports()))
    resultados.append(("Cache Manager", await testar_cache()))
    resultados.append(("Queue Manager", await testar_queue_manager()))
    resultados.append(("Database", await testar_database()))
    resultados.append(("Sync System", await testar_sync_system()))
    resultados.append(("DB Operations", await testar_db_operations()))
    resultados.append(("Performance", await teste_performance()))
    
    # Resumo
    print(f"\n{Cores.NEGRITO}{'=' * 60}")
    print("📊 RESUMO DOS TESTES")
    print("=" * 60)
    
    total = len(resultados)
    passou = sum(1 for _, result in resultados if result)
    falhou = total - passou
    
    for nome, resultado in resultados:
        status = f"{Cores.VERDE}PASSOU{Cores.RESET}" if resultado else f"{Cores.VERMELHO}FALHOU{Cores.RESET}"
        print(f"  {nome:<20} {status}")
    
    print(f"\n{Cores.NEGRITO}Total: {passou}/{total} testes passaram{Cores.RESET}")
    
    if falhou == 0:
        print(f"\n{Cores.VERDE}{Cores.NEGRITO}✅ SISTEMA ESTÁ 100% FUNCIONAL!{Cores.RESET}")
        print("\nVocê pode proceder com a integração no bot.py")
        print("Siga as instruções em INTEGRACAO_GUIA.md")
        return 0
    else:
        print(f"\n{Cores.VERMELHO}{Cores.NEGRITO}❌ {falhou} TESTE(S) FALHARAM{Cores.RESET}")
        print("\nVerifique os erros acima antes de integrar")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
