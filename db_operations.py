"""
Funções de Banco de Dados Otimizadas com Cache
Reduz carga de queries ao usar cache inteligente
"""
from database_v2 import SessionLocal, PartidaDB, JogadorStatsDB
from cache_manager import cache_set, cache_get, cache_invalidate_pattern
import asyncio

# ==========================================
# OPERAÇÕES DE PARTIDA
# ==========================================

async def criar_partida_db(
    canal_id: int,
    modalidade: str,
    valor: float,
    jogador1: str,
    jogador2: str,
    adm_id: str,
    status: str = "Aguardando Pagamento"
) -> bool:
    """Cria nova partida no banco (sem cache pois é nova)"""
    db = SessionLocal()
    try:
        partida = PartidaDB(
            id=canal_id,
            modalidade=modalidade,
            valor=valor,
            jogador1=jogador1,
            jogador2=jogador2,
            status=status,
            adm_id=adm_id
        )
        db.add(partida)
        db.commit()
        
        # Invalidar cache de partidas ativas
        await cache_invalidate_pattern("partida_ativa")
        return True
    except Exception as e:
        db.rollback()
        print(f"❌ Erro ao criar partida: {e}")
        return False
    finally:
        db.close()

async def atualizar_status_partida(canal_id: int, novo_status: str) -> bool:
    """Atualiza status com cache"""
    db = SessionLocal()
    try:
        partida = db.query(PartidaDB).filter(PartidaDB.id == canal_id).first()
        if partida:
            partida.status = novo_status
            db.commit()
            
            # Invalidar cache desta partida
            await cache_set(f"partida_{canal_id}", None, 1)
            await cache_invalidate_pattern("partida_ativa")
            return True
        return False
    except Exception as e:
        db.rollback()
        print(f"❌ Erro ao atualizar status: {e}")
        return False
    finally:
        db.close()

async def obter_partida(canal_id: int) -> dict:
    """Obtém partida com cache (TTL 60s)"""
    # Verificar cache primeiro
    cache_key = f"partida_{canal_id}"
    dados_cache = await cache_get(cache_key)
    if dados_cache is not None:
        return dados_cache
    
    # Se não está em cache, buscar no banco
    db = SessionLocal()
    try:
        partida = db.query(PartidaDB).filter(PartidaDB.id == canal_id).first()
        if partida:
            dados = {
                "id": partida.id,
                "modalidade": partida.modalidade,
                "valor": partida.valor,
                "jogador1": partida.jogador1,
                "jogador2": partida.jogador2,
                "status": partida.status,
                "adm_id": partida.adm_id,
                "data_criacao": str(partida.data_criacao)
            }
            
            # Cachear por 60 segundos
            await cache_set(cache_key, dados, ttl=60)
            return dados
        
        return None
    except Exception as e:
        print(f"❌ Erro ao obter partida: {e}")
        return None
    finally:
        db.close()

# ==========================================
# OPERAÇÕES DE ESTATÍSTICAS
# ==========================================

async def obter_stats_jogador(user_id: str) -> dict:
    """Obtém stats do jogador com cache (TTL 300s)"""
    cache_key = f"stats_jogador_{user_id}"
    
    # Verificar cache
    stats_cache = await cache_get(cache_key)
    if stats_cache is not None:
        return stats_cache
    
    # Buscar no banco
    db = SessionLocal()
    try:
        stats = db.query(JogadorStatsDB).filter(JogadorStatsDB.user_id == str(user_id)).first()
        
        if stats:
            dados = {
                "user_id": stats.user_id,
                "vitorias": stats.vitorias or 0,
                "derrotas": stats.derrotas or 0,
                "wos": stats.wos or 0,
                "saldo_ganho": stats.saldo_ganho or 0.0
            }
        else:
            dados = {
                "user_id": str(user_id),
                "vitorias": 0,
                "derrotas": 0,
                "wos": 0,
                "saldo_ganho": 0.0
            }
        
        # Cachear por 5 minutos
        await cache_set(cache_key, dados, ttl=300)
        return dados
    except Exception as e:
        print(f"❌ Erro ao obter stats: {e}")
        return {}
    finally:
        db.close()

async def atualizar_vitoria(user_id_vencedor: str, user_id_perdedor: str, premios: float) -> bool:
    """Atualiza vitória para ambos (com transação)"""
    db = SessionLocal()
    try:
        # Vencedor
        v = db.query(JogadorStatsDB).filter(JogadorStatsDB.user_id == str(user_id_vencedor)).first()
        if not v:
            v = JogadorStatsDB(user_id=str(user_id_vencedor))
            db.add(v)
        v.vitorias = (v.vitorias or 0) + 1
        v.saldo_ganho = (v.saldo_ganho or 0) + premios
        
        # Perdedor
        p = db.query(JogadorStatsDB).filter(JogadorStatsDB.user_id == str(user_id_perdedor)).first()
        if not p:
            p = JogadorStatsDB(user_id=str(user_id_perdedor))
            db.add(p)
        p.derrotas = (p.derrotas or 0) + 1
        
        db.commit()
        
        # Invalidar cache de ambos
        await cache_invalidate_pattern(f"stats_jogador_{user_id_vencedor}")
        await cache_invalidate_pattern(f"stats_jogador_{user_id_perdedor}")
        return True
    except Exception as e:
        db.rollback()
        print(f"❌ Erro ao atualizar vitória: {e}")
        return False
    finally:
        db.close()

# ==========================================
# OPERAÇÕES EM LOTE
# ==========================================

async def obter_partidas_ativas_em_lote() -> list:
    """Obtém todas as partidas ativas com cache (TTL 30s)"""
    cache_key = "partidas_ativas_lote"
    
    # Verificar cache
    dados_cache = await cache_get(cache_key)
    if dados_cache is not None:
        return dados_cache
    
    # Buscar no banco
    db = SessionLocal()
    try:
        partidas = db.query(PartidaDB).filter(
            PartidaDB.status.in_([
                "Aguardando Pagamento",
                "Jogo Liberado",
                "Aguardando Check-in"
            ])
        ).all()
        
        dados = [
            {
                "id": p.id,
                "modalidade": p.modalidade,
                "valor": p.valor,
                "status": p.status,
                "data_criacao": str(p.data_criacao)
            }
            for p in partidas
        ]
        
        # Cachear por 30 segundos
        await cache_set(cache_key, dados, ttl=30)
        return dados
    except Exception as e:
        print(f"❌ Erro ao obter partidas em lote: {e}")
        return []
    finally:
        db.close()

async def obter_partidas_filtradas(
    status: str = None,
    modalidade: str = None,
    limite: int = 50
) -> list:
    """Obtém partidas com filtros (sem cache, queries muito variadas)"""
    db = SessionLocal()
    try:
        query = db.query(PartidaDB)
        
        if status:
            query = query.filter(PartidaDB.status == status)
        
        if modalidade:
            query = query.filter(PartidaDB.modalidade == modalidade)
        
        partidas = query.order_by(PartidaDB.data_criacao.desc()).limit(limite).all()
        
        return [
            {
                "id": p.id,
                "modalidade": p.modalidade,
                "valor": p.valor,
                "jogador1": p.jogador1,
                "jogador2": p.jogador2,
                "status": p.status,
                "adm_id": p.adm_id,
                "data_criacao": str(p.data_criacao)
            }
            for p in partidas
        ]
    except Exception as e:
        print(f"❌ Erro ao filtrar partidas: {e}")
        return []
    finally:
        db.close()

# ==========================================
# LIMPEZA DE CACHE
# ==========================================

async def limpar_cache_periodo():
    """Task que roda a cada 60s para limpar cache expirado"""
    while True:
        try:
            from cache_manager import cache
            await cache.cleanup_expired()
            await asyncio.sleep(60)
        except Exception as e:
            print(f"❌ Erro na limpeza de cache: {e}")
            await asyncio.sleep(60)
