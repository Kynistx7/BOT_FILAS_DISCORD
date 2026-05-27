import discord
from discord.ext import commands
import os
import asyncio
import random
import re
import io
import qrcode
from dotenv import load_dotenv

from database_v2 import SessionLocal, PartidaDB, JogadorStatsDB, init_db
from queue_manager import queue_manager
from cache_manager import cache, cache_invalidate_pattern
from db_operations import (
    criar_partida_db, atualizar_status_partida, obter_partida,
    obter_stats_jogador, atualizar_vitoria, limpar_cache_periodo
)
from sync_system import event_bus, canais_monitor, EVENTO_PARTIDA_CRIADA, EVENTO_JOGADOR_ENTROU_FILA
from database import Base, engine

# =========================================================
# CONFIGURAÇÃO DE AMBIENTE
# =========================================================
base_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(base_dir, ".env"))

TOKEN = os.getenv("DISCORD_TOKEN")
SECRET = os.getenv("SECRET_KEY")
HOST = os.getenv("DB_HOST")

if not TOKEN:
    raise ValueError("DISCORD_TOKEN não encontrado no .env")

TOKEN = TOKEN.strip()

# =========================================================
# CONSTANTES DO SISTEMA
# =========================================================

# Taxa fixa adicionada ao valor da aposta
TAXA_FIXA = 0.35

# Cargos que podem gerenciar partidas e enviar PIX
CARGOS_STAFF_PERMITIDOS = ["CEO", "Gerente", "Administrador", "ADM", "Staff", "Moderador"]

# IDs das categorias onde os canais de partida serão criados
CATEGORIA_FILAS_MOBILE   = 1507882960597160087
CATEGORIA_FILAS_EMULADOR = 1507882960597160087
CATEGORIA_FILAS_MISTA    = 1507882960597160087

# Valores disponíveis nas filas
VALORES_FILA = ["0.75", "1", "2", "3", "5", "7", "10", "15", "20", "25", "30"]

# Canais de fila com suas respectivas categorias
TODOS_OS_CANAIS = {
    # ── MOBILE ──────────────────────────────────────────
    1507884771634712656: {"nome": "1x1 Mobile",   "valores": VALORES_FILA, "categoria": CATEGORIA_FILAS_MOBILE},
    1507885005072896231: {"nome": "2x2 Mobile",   "valores": VALORES_FILA, "categoria": CATEGORIA_FILAS_MOBILE},
    1507885159846907994: {"nome": "3x3 Mobile",   "valores": VALORES_FILA, "categoria": CATEGORIA_FILAS_MOBILE},
    1507965535478878289: {"nome": "4x4 Mobile",   "valores": VALORES_FILA, "categoria": CATEGORIA_FILAS_MOBILE},
    # ── EMULADOR ─────────────────────────────────────────
    1507967326316789890: {"nome": "1x1 Emulador", "valores": VALORES_FILA, "categoria": CATEGORIA_FILAS_EMULADOR},
    1507967661701730425: {"nome": "2x2 Emulador", "valores": VALORES_FILA, "categoria": CATEGORIA_FILAS_EMULADOR},
    1507968362729439232: {"nome": "3x3 Emulador", "valores": VALORES_FILA, "categoria": CATEGORIA_FILAS_EMULADOR},
    1507968656137650186: {"nome": "4x4 Emulador", "valores": VALORES_FILA, "categoria": CATEGORIA_FILAS_EMULADOR},
    # ── MISTO ────────────────────────────────────────────
    1507973219959967886: {"nome": "2x2 Misto",    "valores": VALORES_FILA, "categoria": CATEGORIA_FILAS_MISTA},
    1507973458120937552: {"nome": "3x3 Misto",    "valores": VALORES_FILA, "categoria": CATEGORIA_FILAS_MISTA},
    1507973697259044974: {"nome": "4x4 Misto",    "valores": VALORES_FILA, "categoria": CATEGORIA_FILAS_MISTA},
}

# Padrões regex para detectar chaves PIX no chat
PADRAO_CPF       = r"\b\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\.\s]?\d{2}\b"
PADRAO_CNPJ      = r"\b\d{2}[\.\s]?\d{3}[\.\s]?\d{3}[\/\.\s]?\d{4}[-\.\s]?\d{2}\b"
PADRAO_TELEFONE  = r"\b(?:\+55\s?)?(?:\(?\d{2}\)?[\s\-]?)(?:9\s?)?\d{4}[\s\-]?\d{4}\b"
PADRAO_EMAIL     = r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
PADRAO_ALEATORIA = r"\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b"

# =========================================================
# ADMINS FINANCEIROS (CHAVES PIX)
# =========================================================
adms = [
    {"id": 1442654638108311562, "pix": "61130967859"},
    {"id": 1490495083446014133, "pix": "11914711528"},
]

def escolher_adm():
    return random.choice(adms)

# =========================================================
# INICIALIZAÇÃO DO BANCO
# =========================================================
try:
    Base.metadata.create_all(bind=engine)
    print("✅ Banco de dados (Base) sincronizado!")
except Exception as e:
    print(f"❌ Erro ao sincronizar Base: {e}")

try:
    init_db()
    print("✅ Banco de dados (init_db) sincronizado!")
except Exception as e:
    print(f"❌ Erro ao inicializar banco: {e}")

# =========================================================
# BOT
# =========================================================
class QueueBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix=["!", "."], intents=intents)
        self.sync_started = False
        self.sincronizacao_cancelamentos_iniciada = False

    async def setup_hook(self):
        print("⚙️ setup_hook executado")

bot = QueueBot()

# Estado em memória
partidas_ativas = {}
painel_mensagens_ids = {}

# =========================================================
# HELPERS DE PERMISSÃO
# =========================================================
def tem_permissao_gerenciar(user: discord.Member, partida: dict) -> bool:
    if user.id == partida["adm"]["id"]:
        return True
    nomes_cargos_usuario = [role.name for role in user.roles]
    for cargo_permitido in CARGOS_STAFF_PERMITIDOS:
        if cargo_permitido in nomes_cargos_usuario:
            return True
    return False

# =========================================================
# VIEWS DO SISTEMA
# =========================================================

class FilaIndividualView(discord.ui.View):
    def __init__(self, canal_id: int, valor: str):
        super().__init__(timeout=None)
        self.canal_id = canal_id
        self.valor = valor

        btn_normal = discord.ui.Button(
            label="🟢 Normal",
            style=discord.ButtonStyle.green,
            custom_id=f"btn_norm_{canal_id}_{valor}"
        )
        btn_full_ump_xm8 = discord.ui.Button(
            label="🔴 Full Ump Xm8",
            style=discord.ButtonStyle.danger,
            custom_id=f"btn_fump_{canal_id}_{valor}"
        )
        btn_sair = discord.ui.Button(
            label="🚪 Sair",
            style=discord.ButtonStyle.secondary,
            custom_id=f"btn_sair_{canal_id}_{valor}"
        )

        btn_normal.callback = self.normal_callback
        btn_full_ump_xm8.callback = self.full_ump_xm8_callback
        btn_sair.callback = self.sair_callback

        self.add_item(btn_normal)
        self.add_item(btn_full_ump_xm8)
        self.add_item(btn_sair)

    async def _entrar_fila(self, interaction: discord.Interaction, tipo: str):
        user = interaction.user
        canal_atual_id = self.canal_id
        valor_atual = self.valor

        sucesso, mensagem = await queue_manager.entrar_fila(
            canal_atual_id, valor_atual, tipo, user
        )

        if not sucesso:
            await interaction.response.send_message(mensagem, ephemeral=True)
            return

        await interaction.response.send_message(mensagem, ephemeral=True)
        await event_bus.emit(EVENTO_JOGADOR_ENTROU_FILA, {
            "usuario": user.id,
            "canal": canal_atual_id,
            "valor": valor_atual
        })

        await atualizar_card_fila(interaction.guild, canal_atual_id, valor_atual)

        fila_info = await queue_manager.obter_fila(canal_atual_id, valor_atual)

        if len(fila_info[tipo]) >= 2:
            try:
                p1, p2 = await queue_manager.remover_usuarios(
                    canal_atual_id, valor_atual, tipo, 2
                )

                nome_modalidade = TODOS_OS_CANAIS[canal_atual_id]["nome"]
                sucesso_partida = await criar_partida(
                    interaction.guild, canal_atual_id, p1, p2, valor_atual, nome_modalidade
                )

                if not sucesso_partida:
                    await queue_manager.entrar_fila(canal_atual_id, valor_atual, tipo, p1)
                    await queue_manager.entrar_fila(canal_atual_id, valor_atual, tipo, p2)
                    await atualizar_card_fila(interaction.guild, canal_atual_id, valor_atual)

            except Exception as e:
                print(f"❌ Erro no Matchmaking: {e}")

    async def normal_callback(self, interaction: discord.Interaction):
        await self._entrar_fila(interaction, "normal")

    async def full_ump_xm8_callback(self, interaction: discord.Interaction):
        await self._entrar_fila(interaction, "fullump")

    async def sair_callback(self, interaction: discord.Interaction):
        user = interaction.user
        canal_atual_id = self.canal_id
        sucesso, mensagem = await queue_manager.sair_fila(canal_atual_id, user)
        await interaction.response.send_message(mensagem, ephemeral=True)
        await atualizar_card_fila(interaction.guild, canal_atual_id, self.valor)


class CheckInView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ Confirmar", style=discord.ButtonStyle.blurple, custom_id="btn_ready")
    async def pronto(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = interaction.channel
        user = interaction.user

        if canal.id not in partidas_ativas:
            await interaction.response.send_message("❌ Esta partida não está mais ativa.", ephemeral=True)
            return

        partida = partidas_ativas[canal.id]

        if user.id != partida["p1"].id and user.id != partida["p2"].id:
            await interaction.response.send_message("❌ Você não faz parte desta partida.", ephemeral=True)
            return

        if user.id in partida["confirmados"]:
            await interaction.response.send_message("⚠️ Você já confirmou sua presença!", ephemeral=True)
            return

        partida["confirmados"].append(user.id)
        await interaction.response.send_message("✅ Presença confirmada! Aguardando o oponente...", ephemeral=True)

        embed = interaction.message.embeds[0]
        status_texto = "✅ Confirmados: " + ", ".join([f"<@{uid}>" for uid in partida["confirmados"]])
        embed.set_field_at(2, name="Confirmações", value=status_texto, inline=False)
        await interaction.message.edit(embed=embed)

        if len(partida["confirmados"]) == 2:
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)

            adm = partida["adm"]
            embed_espera = discord.Embed(
                title=f"⏳ AGUARDANDO LIBERAÇÃO DA STAFF - {partida['modalidade']}",
                description=(
                    f"Os jogadores estão prontos!\n\n"
                    f"👮 **ADM Responsável:** <@{adm['id']}>\n\n"
                    f"O ADM sorteado deve clicar no botão abaixo para disponibilizar sua chave PIX oficial."
                ),
                color=0x3498DB
            )
            embed_espera.add_field(name="⚔️ Confronto", value=f"{partida['p1'].mention} **VS** {partida['p2'].mention}", inline=False)
            embed_espera.add_field(name="💵 Valor por Jogador", value=f"R$ {partida['valor']}", inline=False)

            await canal.send(
                content=f"🔔 <@{adm['id']}> | Os jogadores estão prontos. Libere sua chave PIX!",
                embed=embed_espera,
                view=LiberarPixView()
            )

    @discord.ui.button(label="❌ Cancelar Partida", style=discord.ButtonStyle.danger, custom_id="btn_cancel_checkin")
    async def cancelar_partida(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = interaction.channel
        user = interaction.user

        if canal.id not in partidas_ativas:
            await interaction.response.send_message("❌ Esta partida não está mais ativa.", ephemeral=True)
            return

        partida = partidas_ativas[canal.id]

        if user.id != partida["p1"].id and user.id != partida["p2"].id:
            await interaction.response.send_message("❌ Você não tem permissão para cancelar esta partida.", ephemeral=True)
            return

        embed_cancelado = discord.Embed(
            title="🚫 PARTIDA CANCELADA",
            description=f"O jogador {user.mention} recusou o confronto.\n\n⚠️ Este canal será deletado em **5 segundos**!",
            color=0x7289DA
        )
        await canal.send(embed=embed_cancelado)
        await atualizar_status_partida(canal.id, "Cancelada no Check-in")
        partidas_ativas.pop(canal.id, None)

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        await asyncio.sleep(5)
        try:
            await canal.delete()
        except Exception:
            pass


class LiberarPixView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔓 Liberar Chave PIX", style=discord.ButtonStyle.primary, custom_id="btn_liberar_pix")
    async def liberar_pix(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = interaction.channel

        if canal.id not in partidas_ativas:
            await interaction.response.send_message("❌ Esta partida não está mais ativa.", ephemeral=True)
            return

        partida = partidas_ativas[canal.id]
        valor_base = float(partida["valor"])
        valor_final = round(valor_base + TAXA_FIXA, 2)
        adm = partida["adm"]

        if interaction.user.id != adm["id"]:
            await interaction.response.send_message(
                f"❌ Apenas o ADM sorteado (<@{adm['id']}>) pode liberar esta chave.",
                ephemeral=True
            )
            return

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        arquivo_qrcode = None
        try:
            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(adm["pix"])
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            arquivo_qrcode = discord.File(fp=buffer, filename="qrcode_pix_real.png")
        except Exception as e:
            print(f"❌ Erro ao gerar QR Code: {e}")

        embed_pagamento = discord.Embed(
            title=f"💰 DADOS DE PAGAMENTO LIBERADOS - {partida['modalidade']}",
            description="O ADM validou a presença. Escaneie o QR Code ou copie a chave abaixo.\nEnvie o comprovante aqui no chat e aguarde a liberação.",
            color=0xff0000
        )
        embed_pagamento.add_field(name="⚔️ Confronto", value=f"{partida['p1'].mention} **VS** {partida['p2'].mention}", inline=False)
        embed_pagamento.add_field(name="💵 Valor por Jogador", value=f"R$ {valor_final:.2f}", inline=False)
        embed_pagamento.add_field(name="🔑 Chave PIX Oficial", value=f"`{adm['pix']}`", inline=False)
        embed_pagamento.add_field(name="👮 ADM Fiscal", value=f"<@{adm['id']}>", inline=False)

        if arquivo_qrcode:
            embed_pagamento.set_image(url="attachment://qrcode_pix_real.png")

        try:
            await interaction.message.delete()
        except Exception:
            pass

        await canal.send(
            content=f"{partida['p1'].mention} {partida['p2'].mention} | Chave liberada pelo ADM!",
            embed=embed_pagamento,
            file=arquivo_qrcode,
            view=PagamentoView()
        )


class PagamentoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💰 Confirmar Pagamento", style=discord.ButtonStyle.green, custom_id="btn_pago")
    async def pago(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = interaction.channel

        if canal.id not in partidas_ativas:
            await interaction.response.send_message("❌ Nenhuma partida ativa neste canal.", ephemeral=True)
            return

        partida = partidas_ativas[canal.id]

        if not tem_permissao_gerenciar(interaction.user, partida):
            await interaction.response.send_message("❌ Você não tem permissão de Staff ou não é o ADM responsável.", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        sucesso_status = await atualizar_status_partida(canal.id, "Jogo Liberado")
        if sucesso_status:
            print("✅ Status atualizado: Jogo Liberado")
        else:
            print("❌ Falha ao atualizar status para Jogo Liberado")

        embed = discord.Embed(
            title="🎮 PAGAMENTO CONFIRMADO - JOGO LIBERADO!",
            description="A staff validou os comprovantes.\nA partida está pronta para começar!\n\nJoguem de forma justa!",
            color=0x00ff00
        )
        embed.add_field(name="Desafiantes", value=f"{partida['p1'].mention} **VS** {partida['p2'].mention}")

        id_adm = partida["adm"]["id"]
        await canal.send(
            content=f"🔔 <@{id_adm}> | Pagamento confirmado, partida liberada!",
            embed=embed,
            view=GerenciarPartidaView()
        )

    @discord.ui.button(label="❌ Cancelar / Estornar", style=discord.ButtonStyle.danger, custom_id="btn_cancelar_pagamento")
    async def cancelar_antes_pagar(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = interaction.channel
        if canal.id not in partidas_ativas:
            return
        partida = partidas_ativas[canal.id]

        if not tem_permissao_gerenciar(interaction.user, partida):
            await interaction.response.send_message("❌ Permissão negada.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🚫 PARTIDA ENCERRADA / CANCELADA",
            description=f"Cancelada por <@{interaction.user.id}> antes do início.\n\n⚠️ Canal será deletado em **5 segundos**!",
            color=0x7289DA
        )
        await canal.send(embed=embed)
        await atualizar_status_partida(canal.id, "Cancelada antes do pagamento")
        partidas_ativas.pop(canal.id, None)

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        await asyncio.sleep(5)
        try:
            await canal.delete()
        except Exception:
            pass


class GerenciarPartidaView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🏆 Vitória Jogador 1", style=discord.ButtonStyle.blurple, custom_id="btn_vitoria_p1")
    async def vitoria_p1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finalizar_com_vencedor(interaction, "p1")

    @discord.ui.button(label="🏆 Vitória Jogador 2", style=discord.ButtonStyle.blurple, custom_id="btn_vitoria_p2")
    async def vitoria_p2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finalizar_com_vencedor(interaction, "p2")

    @discord.ui.button(label="💤 Declarar W.O.", style=discord.ButtonStyle.secondary, custom_id="btn_wo")
    async def declarar_wo(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = interaction.channel
        if canal.id not in partidas_ativas:
            return
        partida = partidas_ativas[canal.id]

        if not tem_permissao_gerenciar(interaction.user, partida):
            await interaction.response.send_message("❌ Permissão negada.", ephemeral=True)
            return

        db = SessionLocal()
        try:
            for player in [partida["p1"], partida["p2"]]:
                p_stats = db.query(JogadorStatsDB).filter(
                    JogadorStatsDB.user_id == str(player.id)
                ).first()
                if not p_stats:
                    p_stats = JogadorStatsDB(user_id=str(player.id))
                    db.add(p_stats)
                p_stats.wos += 1

            partida_banco = db.query(PartidaDB).filter(PartidaDB.id == canal.id).first()
            if partida_banco:
                partida_banco.status = "Cancelada por W.O."
            db.commit()
        except Exception as e:
            print(f"❌ Erro ao salvar W.O no banco: {e}")
            db.rollback()
        finally:
            db.close()

        embed = discord.Embed(
            title="💤 PARTIDA ENCERRADA POR W.O.",
            description=f"Encerrado por <@{interaction.user.id}> (W.O.).\n\n⚠️ Canal será deletado em **5 segundos**!",
            color=0x99AAB5
        )
        await canal.send(embed=embed)
        partidas_ativas.pop(canal.id, None)

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        await asyncio.sleep(5)
        try:
            await canal.delete()
        except Exception:
            pass

    @discord.ui.button(label="🚨 Forçar Encerramento", style=discord.ButtonStyle.danger, custom_id="btn_force_close")
    async def forcar_fechamento(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = interaction.channel
        if canal.id not in partidas_ativas:
            return
        partida = partidas_ativas[canal.id]

        if not tem_permissao_gerenciar(interaction.user, partida):
            await interaction.response.send_message("❌ Permissão negada.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🚨 APOSTA CANCELADA DE EMERGÊNCIA",
            description=f"Cancelada por <@{interaction.user.id}>.\n\n⚠️ Canal será deletado em **5 segundos**!",
            color=0x000000
        )
        await canal.send(embed=embed)
        await atualizar_status_partida(canal.id, "Cancelada via Força")
        partidas_ativas.pop(canal.id, None)

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        await asyncio.sleep(5)
        try:
            await canal.delete()
        except Exception:
            pass

    async def finalizar_com_vencedor(self, interaction: discord.Interaction, jogador_vencedor: str):
        canal = interaction.channel
        if canal.id not in partidas_ativas:
            await interaction.response.send_message("❌ Nenhuma partida ativa encontrada.", ephemeral=True)
            return

        partida = partidas_ativas[canal.id]

        if not tem_permissao_gerenciar(interaction.user, partida):
            await interaction.response.send_message("❌ Apenas administradores autorizados.", ephemeral=True)
            return

        vencedor = partida["p1"] if jogador_vencedor == "p1" else partida["p2"]
        perdedor = partida["p2"] if jogador_vencedor == "p1" else partida["p1"]
        total_premio = float(partida["valor"]) * 2

        sucesso_vitoria = await atualizar_vitoria(
            user_id_vencedor=str(vencedor.id),
            user_id_perdedor=str(perdedor.id),
            premios=total_premio
        )
        sucesso_status = await atualizar_status_partida(canal.id, "Finalizada")

        if sucesso_vitoria and sucesso_status:
            print("✅ Vitória registrada com sucesso!")
        else:
            print("❌ Falha ao registrar vitória ou atualizar status.")

        embed = discord.Embed(
            title=f"🏆 PARTIDA FINALIZADA - {partida['modalidade']}",
            description="Resultado confirmado por staff.",
            color=0xFEE75C
        )
        embed.add_field(name="🥇 Vencedor", value=vencedor.mention, inline=False)
        embed.add_field(name="🥈 Perdedor", value=perdedor.mention, inline=False)
        embed.add_field(name="💰 Prêmio Total", value=f"R$ {total_premio:.2f}", inline=False)

        await canal.send(embed=embed)
        partidas_ativas.pop(canal.id, None)

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        await asyncio.sleep(10)
        try:
            await canal.delete()
        except Exception:
            pass


class PixDinamicoView(discord.ui.View):
    def __init__(self, chave_pix: str):
        super().__init__(timeout=None)
        self.chave_pix = chave_pix

    @discord.ui.button(label="📋 Copiar Chave PIX", style=discord.ButtonStyle.secondary)
    async def copiar_pix(self, interaction: discord.Interaction, button: discord.ui.Button):
        bloco_codigo = f"```\n{self.chave_pix}\n```"
        mensagem = f"{bloco_codigo}\n▲ Clique e segure no bloco acima para copiar!"
        await interaction.response.send_message(content=mensagem, ephemeral=True)


# =========================================================
# FUNÇÕES DE LÓGICA MULTI-CANAL
# =========================================================

async def atualizar_card_fila(guild, canal_id: int, valor: str):
    canal_painel = guild.get_channel(canal_id)
    chave_msg = f"{canal_id}_{valor}"
    msg_id = painel_mensagens_ids.get(chave_msg)

    if canal_painel and msg_id:
        try:
            msg = await canal_painel.fetch_message(msg_id)
            fila_info = await queue_manager.obter_fila(canal_id, valor)
            fila_normal = fila_info["normal"]
            fila_fullump = fila_info["fullump"]
            total_jogadores = len(fila_normal) + len(fila_fullump)

            embed = discord.Embed(
                title=f"💰 MODALIDADE R$ {valor}",
                description=(
                    f"👥 Jogadores na fila atualmente: **{total_jogadores}**\n"
                    f"🟢 Normal: **{len(fila_normal)}** | 🔴 Full Ump Xm8: **{len(fila_fullump)}**"
                ),
                color=0x5865F2
            )
            if fila_normal:
                embed.add_field(name="🟢 Normal", value=", ".join([u.mention for u in fila_normal]), inline=False)
            if fila_fullump:
                embed.add_field(name="🔴 Full Ump Xm8", value=", ".join([u.mention for u in fila_fullump]), inline=False)
            if not fila_normal and not fila_fullump:
                embed.add_field(name="Nenhuma fila ativa", value="Ainda não há jogadores em nenhuma seleção.", inline=False)

            await msg.edit(embed=embed, view=FilaIndividualView(canal_id, valor))
        except Exception as e:
            print(f"❌ Erro ao atualizar painel {chave_msg}: {e}")


async def iniciar_painel_completo(guild):
    for canal_id, dados in TODOS_OS_CANAIS.items():
        canal_alvo = guild.get_channel(canal_id)
        if not canal_alvo:
            print(f"⚠️ Canal ID {canal_id} não encontrado no servidor.")
            continue

        try:
            await canal_alvo.purge(limit=30)
            await asyncio.sleep(1.5)

            embed_topo = discord.Embed(
                title=f"🎮 CENTRAL DE APOSTAS - {dados['nome']}",
                description=(
                    "Escolha a fila Normal ou Full Ump Xm8.\n"
                    "As filas são separadas e só confirmam partida quando dois jogadores escolherem a mesma opção."
                ),
                color=0x2f3136
            )
            await canal_alvo.send(embed=embed_topo)

            for valor in reversed(dados["valores"]):
                embed_fila = discord.Embed(
                    title=f"💰 MODALIDADE R$ {valor}",
                    description="👥 Jogadores na fila atualmente: **0**",
                    color=0x5865F2
                )
                msg = await canal_alvo.send(embed=embed_fila, view=FilaIndividualView(canal_id, valor))
                painel_mensagens_ids[f"{canal_id}_{valor}"] = msg.id

            await asyncio.sleep(1.5)

        except discord.HTTPException as e:
            if e.status == 429:
                retry = getattr(e, "retry_after", 5) or 5
                print(f"⚠️ Rate limit no canal {canal_id}. Aguardando {retry}s...")
                await asyncio.sleep(retry)
            else:
                print(f"❌ Erro HTTP ao iniciar painel no canal {canal_id}: {e}")
        except Exception as e:
            print(f"❌ Erro ao iniciar painel no canal {canal_id}: {e}")


async def criar_partida(guild, canal_origem_id: int, p1, p2, valor, modalidade_nome) -> bool:
    # Busca a categoria correta com base no canal de fila de origem
    categoria_id = TODOS_OS_CANAIS.get(canal_origem_id, {}).get("categoria")
    if not categoria_id:
        print(f"❌ Categoria não encontrada para o canal {canal_origem_id}!")
        return False

    categoria = guild.get_channel(categoria_id)
    if not categoria:
        print(f"❌ Categoria ID {categoria_id} não encontrada no servidor!")
        return False

    if not await canais_monitor.pode_usar_canal(categoria_id):
        return False

    prefixo_nome = modalidade_nome.lower().replace(" ", "-")
    nome_sala = f"{prefixo_nome}-{random.randint(1000, 9999)}"

    adm_escolhido = escolher_adm()
    adm_usuario = guild.get_member(adm_escolhido["id"])

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        p1: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, embed_links=True),
        p2: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, embed_links=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
    }
    if adm_usuario:
        overwrites[adm_usuario] = discord.PermissionOverwrite(
            read_messages=True, send_messages=True, attach_files=True, embed_links=True
        )

    try:
        novo_canal = await guild.create_text_channel(
            name=nome_sala, category=categoria, overwrites=overwrites
        )
    except Exception as e:
        await canais_monitor.registrar_operacao(categoria_id, sucesso=False)
        print(f"❌ Erro ao criar canal de partida: {e}")
        return False

    sucesso_db = await criar_partida_db(
        canal_id=novo_canal.id,
        modalidade=modalidade_nome,
        valor=float(valor),
        jogador1=p1.name,
        jogador2=p2.name,
        adm_id=str(adm_escolhido["id"])
    )

    if not sucesso_db:
        await canais_monitor.registrar_operacao(novo_canal.id, sucesso=False)
        try:
            await novo_canal.delete(reason="Falha ao registrar partida no banco")
        except Exception:
            pass
        return False

    await canais_monitor.registrar_operacao(novo_canal.id, sucesso=True)
    await event_bus.emit(EVENTO_PARTIDA_CRIADA, {
        "canal_id": novo_canal.id,
        "jogador1": p1.id,
        "jogador2": p2.id,
        "valor": valor
    })

    partidas_ativas[novo_canal.id] = {
        "p1": p1,
        "p2": p2,
        "valor": valor,
        "modalidade": modalidade_nome,
        "confirmados": [],
        "adm": adm_escolhido
    }

    embed_checkin = discord.Embed(
        title=f"⚔️ CONFRONTO ENCONTRADO - {modalidade_nome}",
        description=(
            f"Os jogadores foram pareados!\n\n"
            f"👉 {p1.mention} **VS** {p2.mention}\n"
            f"💵 **Valor da Entrada:** R$ {valor}\n\n"
            f"⚠️ Vocês têm até **2 minutos** para confirmar ou a partida será cancelada por timeout."
        ),
        color=0xE74C3C
    )
    embed_checkin.add_field(name="🏆 Premiação Bruta", value=f"R$ {float(valor) * 2:.2f}", inline=True)
    embed_checkin.add_field(name="👮 Fiscal de Mesa", value=f"<@{adm_escolhido['id']}>", inline=True)
    embed_checkin.add_field(name="Confirmações", value="⏳ Aguardando ambos os jogadores...", inline=False)

    await novo_canal.send(
        content=f"{p1.mention} {p2.mention} | Confirmem presença!",
        embed=embed_checkin,
        view=CheckInView()
    )

    # Inicia o timeout de 2 minutos para o check-in
    await iniciar_timeout_partida(novo_canal.id)

    return True


# =========================================================
# TIMEOUT AUTOMÁTICO DE CHECK-IN
# =========================================================
async def timeout_checkin(canal_id: int):
    await asyncio.sleep(120)

    if canal_id not in partidas_ativas:
        return

    canal = bot.get_channel(canal_id)
    if not canal:
        return

    partida = partidas_ativas[canal_id]

    if len(partida["confirmados"]) < 2:
        try:
            embed = discord.Embed(
                title="⌛ CHECK-IN EXPIRADO",
                description="Os jogadores não confirmaram a tempo.\n\n⚠️ Canal será deletado em 5 segundos.",
                color=0xff0000
            )
            await canal.send(embed=embed)
            await atualizar_status_partida(canal_id, "Cancelada por Timeout")
            partidas_ativas.pop(canal_id, None)
            await asyncio.sleep(5)
            await canal.delete()
        except Exception as e:
            print(f"❌ Erro no timeout de check-in: {e}")


async def iniciar_timeout_partida(canal_id: int):
    bot.loop.create_task(timeout_checkin(canal_id))


# =========================================================
# SINCRONIZAÇÃO DE CANCELAMENTOS VIA WEB
# =========================================================
async def sincronizar_cancelamentos_via_web_v2():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            db = SessionLocal()
            try:
                partidas_canceladas = db.query(PartidaDB).filter(
                    PartidaDB.status == "Cancelada via Web"
                ).limit(10).all()

                for partida in partidas_canceladas:
                    canal_id = partida.id

                    if not await canais_monitor.pode_usar_canal(canal_id):
                        print(f"⛔ Canal {canal_id} isolado, pulando...")
                        continue

                    canal = bot.get_channel(canal_id)
                    partidas_ativas.pop(canal_id, None)

                    if canal:
                        try:
                            await canal.send("🚫 Cancelada via painel web")
                            await asyncio.sleep(1)
                            await canal.delete(reason="Cancelada via web")
                            await canais_monitor.registrar_operacao(canal_id, sucesso=True)
                            print(f"✅ Canal {canal_id} deletado via web")
                        except Exception as e:
                            await canais_monitor.registrar_operacao(canal_id, sucesso=False)
                            print(f"❌ Erro ao deletar canal {canal_id}: {e}")
            finally:
                db.close()

        except Exception as e:
            print(f"❌ Erro na sincronização web: {e}")

        await asyncio.sleep(30)


# =========================================================
# COMANDOS
# =========================================================

@bot.command(name="p", aliases=["perfil", "stats"])
async def perfil_jogador(ctx, membro: discord.Member = None):
    """Exibe o histórico competitivo de um usuário."""
    usuario_alvo = membro or ctx.author

    db = SessionLocal()
    try:
        stats = db.query(JogadorStatsDB).filter(
            JogadorStatsDB.user_id == str(usuario_alvo.id)
        ).first()

        vitorias = stats.vitorias if stats else 0
        derrotas = stats.derrotas if stats else 0
        wos = stats.wos if stats else 0
        saldo = stats.saldo_ganho if stats else 0.0

        total_jogos = vitorias + derrotas
        winrate = (vitorias / total_jogos * 100) if total_jogos > 0 else 0.0

        embed = discord.Embed(
            title=f"📊 HISTÓRICO PROFISSIONAL - {usuario_alvo.display_name}",
            description=f"Estatísticas de {usuario_alvo.mention}",
            color=0x5865F2
        )

        if usuario_alvo.avatar:
            embed.set_thumbnail(url=usuario_alvo.avatar.url)

        embed.add_field(name="🏆 Vitórias",        value=f"`{vitorias}`",         inline=True)
        embed.add_field(name="❌ Derrotas",         value=f"`{derrotas}`",         inline=True)
        embed.add_field(name="💤 W.O.",             value=f"`{wos}`",              inline=True)
        embed.add_field(name="🎮 Total de Partidas",value=f"`{total_jogos}`",      inline=True)
        embed.add_field(name="📈 Winrate",          value=f"`{winrate:.1f}%`",     inline=True)
        embed.add_field(name="💰 Lucro Bruto",      value=f"`R$ {saldo:.2f}`",     inline=True)

        if total_jogos > 0:
            blocos_verdes = int(winrate // 10)
            blocos_vermelhos = 10 - blocos_verdes
            barra_visual = "🟩" * blocos_verdes + "🟥" * blocos_vermelhos
            embed.add_field(name="📊 Aproveitamento", value=barra_visual, inline=False)
        else:
            embed.add_field(name="📊 Aproveitamento", value="⬜" * 10 + " (Sem dados)", inline=False)

        embed.set_footer(text=f"ID: {usuario_alvo.id}")
        await ctx.send(embed=embed)

    except Exception as e:
        print(f"❌ Erro ao processar perfil: {e}")
        await ctx.send("❌ Não foi possível carregar as estatísticas.")
    finally:
        db.close()


@bot.command(name="setup")
@commands.has_any_role("CEO", "Gerente", "Administrador", "ADM")
async def setup_paineis(ctx):
    try:
        await iniciar_painel_completo(ctx.guild)
        embed = discord.Embed(
            title="✅ PAINÉIS CRIADOS",
            description="Todos os painéis foram configurados com sucesso.",
            color=0x00ff00
        )
        await ctx.send(embed=embed)
    except Exception as e:
        print(f"❌ Erro no setup: {e}")
        await ctx.send(f"❌ Erro ao configurar painéis.\n```{e}```")


@bot.command(name="resetfilas")
@commands.has_permissions(administrator=True)
async def reset_filas(ctx):
    try:
        await queue_manager.limpar_tudo()
        for canal_id, dados in TODOS_OS_CANAIS.items():
            for valor in dados["valores"]:
                try:
                    await atualizar_card_fila(ctx.guild, canal_id, valor)
                except Exception:
                    pass
        await ctx.send("🧹 Todas as filas foram resetadas.")
    except Exception as e:
        print(f"❌ Erro resetando filas: {e}")
        await ctx.send(f"❌ Erro ao resetar filas.\n```{e}```")


@bot.command(name="syncweb")
@commands.has_permissions(administrator=True)
async def sync_web(ctx):
    await ctx.send("🔄 Executando sincronização manual...")
    try:
        db = SessionLocal()
        try:
            partidas_canceladas = db.query(PartidaDB).filter(
                PartidaDB.status == "Cancelada via Web"
            ).all()
            total = 0
            for partida in partidas_canceladas:
                canal = bot.get_channel(partida.id)
                if canal:
                    try:
                        await canal.delete(reason="Cancelada via painel web")
                        total += 1
                    except Exception as e:
                        print(f"❌ Erro ao deletar canal {partida.id}: {e}")
        finally:
            db.close()
        await ctx.send(f"✅ Sincronização concluída. {total} canais removidos.")
    except Exception as e:
        await ctx.send(f"❌ Erro na sincronização.\n```{e}```")


# =========================================================
# EVENTOS
# =========================================================

@bot.event
async def on_ready():
    print("=" * 60)
    print(f"🟢 BOT ONLINE: {bot.user}")
    print(f"🧠 Servidores conectados: {len(bot.guilds)}")
    print("=" * 60)

    if not bot.sincronizacao_cancelamentos_iniciada:
        for canal_id, dados in TODOS_OS_CANAIS.items():
            queue_manager.inicializar_canal(canal_id, dados["valores"])

        bot.loop.create_task(limpar_cache_periodo())
        bot.loop.create_task(sincronizar_cancelamentos_via_web_v2())

        bot.sincronizacao_cancelamentos_iniciada = True
        print("✅ Sistema de cache + monitoramento iniciado!")

    print("✅ Bot carregado com sucesso!")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    try:
        texto = message.content
        encontrou_pix = (
            re.search(PADRAO_CPF, texto)
            or re.search(PADRAO_CNPJ, texto)
            or re.search(PADRAO_TELEFONE, texto)
            or re.search(PADRAO_EMAIL, texto)
            or re.search(PADRAO_ALEATORIA, texto)
        )

        if encontrou_pix:
            cargos_usuario = [role.name for role in message.author.roles]
            eh_staff = any(cargo in cargos_usuario for cargo in CARGOS_STAFF_PERMITIDOS)

            if not eh_staff:
                try:
                    await message.delete()
                except Exception:
                    pass

                aviso = await message.channel.send(
                    f"🚫 {message.author.mention} apenas administradores podem enviar chaves PIX."
                )
                await asyncio.sleep(5)
                try:
                    await aviso.delete()
                except Exception:
                    pass

    except Exception as e:
        print(f"❌ Erro no anti-pix: {e}")

    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Você não possui permissão para isso.")
    elif isinstance(error, commands.MissingAnyRole):
        await ctx.send("❌ Você não possui o cargo necessário para este comando.")
    else:
        print(f"❌ Erro global: {error}")
        await ctx.send(f"❌ Ocorreu um erro.\n```{error}```")


# =========================================================
# INICIALIZAÇÃO FINAL
# =========================================================
if __name__ == "__main__":
    print("🚀 Iniciando bot...")
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Erro fatal: {e}")