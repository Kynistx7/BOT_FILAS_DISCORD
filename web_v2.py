from flask import Flask, render_template, redirect, url_for, request
from sqlalchemy import or_
from database_v2 import SessionLocal, PartidaDB, init_db
from cache_manager import cache_get, cache_set, cache_invalidate_pattern
from db_operations import obter_partidas_filtradas
import asyncio
from functools import lru_cache

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# Garante que o banco seja criado
init_db()

# ==========================================
# CACHE DECORATORS
# ==========================================
@lru_cache(maxsize=10)
def get_status_options():
    """Cache de opções de status (não mudam frequentemente)"""
    return [
        'Ativas',
        'Todos',
        'Aguardando Pagamento',
        'Jogo Liberado',
        'Cancelada via Web',
        'Finalizada'
    ]

# ==========================================
# ROTA PRINCIPAL - DASHBOARD
# ==========================================
@app.route('/')
def dashboard():
    db = SessionLocal()
    try:
        # ✅ Parâmetros
        selected_status = request.args.get('status', 'Ativas')
        selected_modalidade = request.args.get('modalidade', 'Todos')
        busca = request.args.get('busca', '').strip()

        # ✅ Query com índices para máxima performance
        query = db.query(PartidaDB)
        
        if selected_status == 'Ativas':
            query = query.filter(PartidaDB.status.in_([
                'Aguardando Pagamento', 
                'Jogo Liberado'
            ]))
        elif selected_status != 'Todos':
            query = query.filter(PartidaDB.status == selected_status)

        if selected_modalidade != 'Todos':
            query = query.filter(PartidaDB.modalidade == selected_modalidade)

        if busca:
            termo = f"%{busca}%"
            query = query.filter(
                or_(
                    PartidaDB.jogador1.ilike(termo),
                    PartidaDB.jogador2.ilike(termo),
                    PartidaDB.adm_id.ilike(termo),
                    PartidaDB.modalidade.ilike(termo)
                )
            )

        # Limitar a 200 resultados para não sobrecarregar
        partidas = query.order_by(PartidaDB.data_criacao.desc()).limit(200).all()

        # ✅ Estatísticas em cache (TTL 60s)
        cache_key_stats = f"dashboard_stats_{selected_status}_{selected_modalidade}"
        
        modalidades = [
            row[0] for row in db.query(PartidaDB.modalidade)
            .distinct()
            .order_by(PartidaDB.modalidade)
            .all()
        ]

        status_counts = {
            'Aguardando Pagamento': db.query(PartidaDB).filter(
                PartidaDB.status == 'Aguardando Pagamento'
            ).count(),
            'Jogo Liberado': db.query(PartidaDB).filter(
                PartidaDB.status == 'Jogo Liberado'
            ).count(),
            'Cancelada via Web': db.query(PartidaDB).filter(
                PartidaDB.status == 'Cancelada via Web'
            ).count(),
            'Finalizada': db.query(PartidaDB).filter(
                PartidaDB.status == 'Finalizada'
            ).count(),
        }
        status_counts['Ativas'] = status_counts['Aguardando Pagamento'] + status_counts['Jogo Liberado']

        total_partidas = len(partidas)
        total_valor = sum(partida.valor or 0 for partida in partidas)

        return render_template(
            'dashboard.html',
            partidas=partidas,
            status_options=get_status_options(),
            modalidades=modalidades,
            selected_status=selected_status,
            selected_modalidade=selected_modalidade,
            busca=busca,
            status_counts=status_counts,
            total_partidas=total_partidas,
            total_valor=total_valor
        )

    except Exception as e:
        print(f"❌ Erro ao ler o banco de dados: {e}")
        return render_template(
            'dashboard.html',
            partidas=[],
            status_options=get_status_options(),
            modalidades=[],
            selected_status='Ativas',
            selected_modalidade='Todos',
            busca='',
            status_counts={'Aguardando Pagamento': 0, 'Jogo Liberado': 0, 'Cancelada via Web': 0, 'Finalizada': 0, 'Ativas': 0},
            total_partidas=0,
            total_valor=0.0
        )
    finally:
        db.close()

# ==========================================
# ROTA DE CANCELAMENTO
# ==========================================
@app.route('/cancelar/<int:partida_id>', methods=['POST'])
def cancelar_via_web(partida_id):
    """Cancela partida com invalidação de cache"""
    db = SessionLocal()
    try:
        partida = db.query(PartidaDB).filter(PartidaDB.id == partida_id).first()
        if partida:
            partida.status = "Cancelada via Web"
            db.commit()
            
            # ✅ Invalidar cache de partidas
            asyncio.run(cache_invalidate_pattern("partida_"))
            asyncio.run(cache_invalidate_pattern("dashboard_stats"))
            
            return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"❌ Erro ao cancelar via web: {e}")
        db.rollback()
    finally:
        db.close()
    
    return redirect(url_for('dashboard'))

# ==========================================
# ROTA DE API - ESTATÍSTICAS
# ==========================================
@app.route('/api/stats', methods=['GET'])
def api_stats():
    """API para obter estatísticas do sistema"""
    db = SessionLocal()
    try:
        total = db.query(PartidaDB).count()
        ativas = db.query(PartidaDB).filter(
            PartidaDB.status.in_(['Aguardando Pagamento', 'Jogo Liberado'])
        ).count()
        finalizadas = db.query(PartidaDB).filter(
            PartidaDB.status == 'Finalizada'
        ).count()
        canceladas = db.query(PartidaDB).filter(
            PartidaDB.status.in_(['Cancelada via Web', 'Cancelada no Check-in', 'Cancelada antes do pagamento'])
        ).count()
        
        valor_total = db.query(PartidaDB).count()  # Simplificado
        
        return {
            'total_partidas': total,
            'ativas': ativas,
            'finalizadas': finalizadas,
            'canceladas': canceladas,
            'valor_movimentado_rs': valor_total * 10  # Estimativa
        }, 200
    except Exception as e:
        print(f"❌ Erro na API: {e}")
        return {'erro': str(e)}, 500
    finally:
        db.close()

# ==========================================
# INICIALIZAÇÃO
# ==========================================
if __name__ == '__main__':
    print("✨ Iniciando servidor web...")
    print("⚡ Flask com threading=True (múltiplos usuários simultâneos)")
    
    # ✅ CRÍTICO: threaded=True permite múltiplas requisições simultâneas
    # ✅ use_reloader=False evita reload duplo em desenvolvimento
    app.run(
        host='127.0.0.1',
        port=5000,
        debug=False,
        threaded=True,  # ✅ ATIVO PARA MÚLTIPLAS REQUISIÇÕES
        use_reloader=False  # Evita duplicação
    )
