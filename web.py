from flask import Flask, render_template, redirect, url_for, request
from sqlalchemy import or_
from database import SessionLocal, PartidaDB, init_db

app = Flask(__name__)

# Garante que o banco e as tabelas sejam criados antes do site abrir
init_db()

@app.route('/')
def dashboard():
    db = SessionLocal()
    try:
        total_partidas_db = db.query(PartidaDB).count()

        selected_status = request.args.get('status', 'Ativas')
        selected_modalidade = request.args.get('modalidade', 'Todos')
        busca = request.args.get('busca', '').strip()

        status_options = [
            'Ativas',
            'Todos',
            'Aguardando Pagamento',
            'Jogo Liberado',
            'Cancelada via Web',
            'Finalizada'
        ]

        query = db.query(PartidaDB)
        if selected_status == 'Ativas':
            query = query.filter(PartidaDB.status.in_(['Aguardando Pagamento', 'Jogo Liberado']))
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

        partidas = query.order_by(PartidaDB.data_criacao.desc()).all()
        modalidades = [row[0] for row in db.query(PartidaDB.modalidade).distinct().order_by(PartidaDB.modalidade).all()]

        if total_partidas_db == 0:
            partida_teste = PartidaDB(
                id=999999,
                modalidade="X1 TESTE PAINEL",
                valor=10.00,
                jogador1="Jogador_A",
                jogador2="Jogador_B",
                status="Aguardando Pagamento",
                adm_id="123456789"
            )
            db.add(partida_teste)
            db.commit()
            partidas = db.query(PartidaDB).order_by(PartidaDB.data_criacao.desc()).all()
            modalidades = [row[0] for row in db.query(PartidaDB.modalidade).distinct().order_by(PartidaDB.modalidade).all()]

        status_counts = {
            'Aguardando Pagamento': db.query(PartidaDB).filter(PartidaDB.status == 'Aguardando Pagamento').count(),
            'Jogo Liberado': db.query(PartidaDB).filter(PartidaDB.status == 'Jogo Liberado').count(),
            'Cancelada via Web': db.query(PartidaDB).filter(PartidaDB.status == 'Cancelada via Web').count(),
            'Finalizada': db.query(PartidaDB).filter(PartidaDB.status == 'Finalizada').count(),
            'Ativas': db.query(PartidaDB).filter(PartidaDB.status.in_(['Aguardando Pagamento', 'Jogo Liberado'])).count()
        }

        total_partidas = len(partidas)
        total_valor = sum(partida.valor or 0 for partida in partidas)

    except Exception as e:
        print(f"❌ Erro ao ler o banco de dados: {e}")
        partidas = []
        status_options = []
        modalidades = []
        selected_status = 'Ativas'
        selected_modalidade = 'Todos'
        busca = ''
        status_counts = {'Aguardando Pagamento': 0, 'Jogo Liberado': 0, 'Cancelada via Web': 0, 'Finalizada': 0, 'Ativas': 0}
        total_partidas = 0
        total_valor = 0.0
    finally:
        db.close() # Sempre fecha a conexão para não travar o banco

    return render_template(
        'dashboard.html',
        partidas=partidas,
        status_options=status_options,
        modalidades=modalidades,
        selected_status=selected_status,
        selected_modalidade=selected_modalidade,
        busca=busca,
        status_counts=status_counts,
        total_partidas=total_partidas,
        total_valor=total_valor
    )

@app.route('/cancelar/<int:partida_id>')
def cancelar_via_web(partida_id):
    db = SessionLocal()
    partida = db.query(PartidaDB).filter(PartidaDB.id == partida_id).first()
    if partida:
        partida.status = "Cancelada via Web"
        db.commit()
    db.close()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    print("✨ Iniciando o servidor do painel web...")
    # Desativamos o 'threaded=True' e adicionamos controle de porta limpa
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=False)