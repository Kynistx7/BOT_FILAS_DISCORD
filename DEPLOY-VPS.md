# 🚀 Guia de Deploy - Bot Discord no VPS IONOS

## 📋 Pré-requisitos

- VPS S IONOS com acesso SSH
- Token do bot Discord
- Banco de dados MySQL/PostgreSQL (ou usar SQLite local)

## 🔧 Passo 1: Conectar ao VPS via SSH

```bash
ssh usuario@seu_ip_vps
```

## 📥 Passo 2: Fazer Upload dos Arquivos

Use SFTP ou SCP para copiar os arquivos:

```bash
# De seu computador local
scp -r bot.py database.py web.py templates/ static/ .env requirements.txt usuario@seu_ip_vps:~/bot_filas/
```

Ou use um cliente SFTP (FileZilla, WinSCP).

## 🏗️ Passo 3: Executar Script de Setup

No VPS, execute:

```bash
cd ~/bot_filas
bash setup-vps.sh
```

## 🔐 Passo 4: Configurar Variáveis de Ambiente

Edite o arquivo `.env`:

```bash
nano .env
```

Adicione:
```
DISCORD_TOKEN=seu_token_aqui
SECRET_KEY=sua_chave_secreta_aqui
DB_HOST=localhost_ou_seu_host
DB_USER=seu_usuario_banco
DB_PASSWORD=sua_senha_banco
DB_NAME=nome_banco_dados
```

## ⚙️ Passo 5: Iniciar o Bot como Serviço

### Ativar o serviço systemd:

```bash
sudo systemctl enable bot-discord
sudo systemctl start bot-discord
```

### Ver status:

```bash
sudo systemctl status bot-discord
```

### Ver logs em tempo real:

```bash
sudo journalctl -u bot-discord -f
```

## 🛠️ Comandos Úteis

| Comando | Função |
|---------|--------|
| `sudo systemctl start bot-discord` | Iniciar bot |
| `sudo systemctl stop bot-discord` | Parar bot |
| `sudo systemctl restart bot-discord` | Reiniciar bot |
| `sudo systemctl status bot-discord` | Ver status |
| `sudo journalctl -u bot-discord -f` | Ver logs ao vivo |
| `sudo journalctl -u bot-discord --lines=100` | Ver últimas 100 linhas |

## 🔄 Atualizar o Bot

Quando fizer mudanças no código:

```bash
# No VPS
cd ~/bot_filas
# Copie os arquivos atualizados
sudo systemctl restart bot-discord
```

## 🐛 Troubleshooting

### Bot não inicia
```bash
sudo journalctl -u bot-discord -n 50
```

### Erro de permissão
```bash
sudo chown -R $USER:$USER ~/bot_filas
chmod +x setup-vps.sh
```

### Limpar logs antigos
```bash
sudo journalctl --vacuum=time=7d
```

## 💾 Backup do Banco de Dados

Se usar MySQL:
```bash
mysqldump -u usuario -p nome_banco > backup.sql
```

Se usar SQLite:
```bash
cp database.db backup_$(date +%Y%m%d).db
```

## 📊 Monitorar Recursos

```bash
htop
```

## ✅ Verificar se o Bot está Online

1. Vá ao seu servidor Discord
2. Verifique se o bot aparece como "Online"
3. Teste um comando

---

**Suporte:** Se tiver problemas, verifique os logs com `journalctl`
