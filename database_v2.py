import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Index
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool

# ==========================================
# CONFIGURAÇÃO DE BANCO OTIMIZADA
# ==========================================
DATABASE_URL = "sqlite:///partidas.db"

# Pool de conexões para melhor performance
# QueuePool: ideal para SQLite em VPS
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Valida conexões antes de usar
    echo=False  # Mude para True para debug
)

Base = declarative_base()

# ==========================================
# TABELA DE PARTIDAS
# ==========================================
class PartidaDB(Base):
    __tablename__ = 'partidas'
    
    id = Column(Integer, primary_key=True)
    modalidade = Column(String(50), nullable=False)
    valor = Column(Float, nullable=False)
    jogador1 = Column(String(100), nullable=False)
    jogador2 = Column(String(100), nullable=False)
    status = Column(String(50), default="Aguardando Pagamento", nullable=False)
    adm_id = Column(String(50), nullable=False)
    data_criacao = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

# Índices para queries frequentes
Index('idx_partida_status', PartidaDB.status)
Index('idx_partida_data', PartidaDB.data_criacao)
Index('idx_partida_modalidade', PartidaDB.modalidade)
Index('idx_partida_adm', PartidaDB.adm_id)
Index('idx_partida_status_data', PartidaDB.status, PartidaDB.data_criacao)

# ==========================================
# TABELA DE ESTATÍSTICAS
# ==========================================
class JogadorStatsDB(Base):
    __tablename__ = "jogador_stats"
    
    user_id = Column(String(50), primary_key=True)
    vitorias = Column(Integer, default=0, nullable=False)
    derrotas = Column(Integer, default=0, nullable=False)
    wos = Column(Integer, default=0, nullable=False)
    saldo_ganho = Column(Float, default=0.0, nullable=False)

# Índice para stats mais comuns
Index('idx_jogador_winrate', JogadorStatsDB.vitorias, JogadorStatsDB.derrotas)

# ==========================================
# SESSÃO OTIMIZADA
# ==========================================
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False  # Evita queries extras
)

def init_db():
    """Cria tabelas e índices"""
    Base.metadata.create_all(bind=engine)
    print("✅ Banco de dados inicializado com sucesso!")

def obter_sessao():
    """Context manager para sessão segura"""
    sessao = SessionLocal()
    try:
        yield sessao
        sessao.commit()
    except Exception as e:
        sessao.rollback()
        print(f"❌ Erro na sessão: {e}")
        raise
    finally:
        sessao.close()
