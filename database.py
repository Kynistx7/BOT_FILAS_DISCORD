import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker



# Nome do arquivo de banco de dados local que será gerado automaticamente
DATABASE_URL = "sqlite:///partidas.db"

Base = declarative_base()

# ==========================================
# ESTRUTURA DA TABELA DE PARTIDAS DO BANCO
# ==========================================
class PartidaDB(Base):
    __tablename__ = 'partidas'
    
    id = Column(Integer, primary_key=True)                        # ID do canal do Discord
    modalidade = Column(String(50))                              # X1, 3x3, 4x4, etc.
    valor = Column(Float)                                        # Valor da aposta
    jogador1 = Column(String(100))                               # Nome do Jogador/Líder 1
    jogador2 = Column(String(100))                               # Nome do Jogador/Líder 2
    status = Column(String(50), default="Aguardando Pagamento")  # Status atual da sala
    adm_id = Column(String(50))                                  # ID do ADM que cuida do PIX
    data_criacao = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

# ==========================================
# NOVA TABELA: ESTATÍSTICAS DO JOGADOR
# ==========================================
class JogadorStatsDB(Base):
    __tablename__ = "jogador_stats"

    user_id = Column(String(50), primary_key=True)               # ID único do Discord do jogador
    vitorias = Column(Integer, default=0)                        # Total de vitórias acumuladas
    derrotas = Column(Integer, default=0)                        # Total de derrotas acumuladas
    wos = Column(Integer, default=0)                             # Total de vitórias/cancelamentos por W.O.
    saldo_ganho = Column(Float, default=0.0)                     # Lucro bruto total acumulado em R$

# ==========================================
# CONEXÃO DO BANCO DE DADOS (THREAD-SAFE)
# ==========================================
# O 'check_same_thread=False' é CRÍTICO para permitir que o Bot do Discord
# e o Painel Web (Flask) acessem o arquivo ao mesmo tempo sem travar.
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

def init_db():
    """Função que cria o arquivo partidas.db e as tabelas caso não existam"""
    Base.metadata.create_all(bind=engine)