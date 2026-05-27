#!/bin/bash

# Script de Setup para Bot Discord no VPS IONOS
# Execute como: bash setup-vps.sh

echo "🚀 Iniciando setup do Bot Discord no VPS..."

# Atualizar sistema
echo "📦 Atualizando pacotes do sistema..."
sudo apt update && sudo apt upgrade -y

# Instalar Python e dependências
echo "🐍 Instalando Python 3.11+..."
sudo apt install -y python3 python3-pip python3-venv git

# Criar diretório do bot
echo "📁 Criando diretório do bot..."
mkdir -p ~/bot_filas
cd ~/bot_filas

# Clonar ou copiar os arquivos
echo "📥 Copie seus arquivos (bot.py, database.py, web.py, templates/, static/) para ~/bot_filas"
echo "   Aguardando..."

# Criar ambiente virtual
echo "🔧 Criando ambiente virtual..."
python3 -m venv venv
source venv/bin/activate

# Instalar dependências Python
echo "📚 Instalando dependências Python..."
pip install --upgrade pip
pip install -r requirements.txt

# Criar arquivo .env
echo "🔐 Criando arquivo .env..."
cat > .env << EOF
DISCORD_TOKEN=SEU_TOKEN_AQUI
SECRET_KEY=SEU_SECRET_KEY_AQUI
DB_HOST=SEU_HOST_BANCO_DE_DADOS_AQUI
EOF

echo "⚠️  Edite o arquivo .env com suas credenciais:"
echo "   nano .env"

# Criar serviço systemd
echo "⚙️  Criando serviço systemd..."
sudo tee /etc/systemd/system/bot-discord.service > /dev/null << EOF
[Unit]
Description=Bot Discord Filas
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/bot_filas
Environment="PATH=$HOME/bot_filas/venv/bin"
ExecStart=$HOME/bot_filas/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

echo "✅ Setup concluído!"
echo ""
echo "📋 Próximos passos:"
echo "1. Edite o arquivo .env com suas credenciais"
echo "2. Para iniciar o bot:"
echo "   sudo systemctl start bot-discord"
echo "3. Para ver logs:"
echo "   sudo journalctl -u bot-discord -f"
echo "4. Para reiniciar:"
echo "   sudo systemctl restart bot-discord"
echo ""
