# Professor AI - English Teacher via WhatsApp

Uma solução inteligente que conecta usuários do WhatsApp a uma IA capaz de ensinar inglês, realizar avaliações, enviar áudios e interagir de forma personalizada. O projeto demonstra domínio em integrações complexas, automação e uso avançado de APIs do Facebook (Meta) e OpenAI.

## 🚀 Funcionalidades
- Avaliação automática do nível de inglês
- Geração de plano de estudos personalizado
- Conversas diárias em texto e áudio
- Exercícios interativos e feedback de pronúncia
- Rastreamento de progresso do usuário
- Respostas automáticas inteligentes via IA
- Conversão de texto para áudio e transcrição de áudios

## 🔌 Integrações e Arquitetura
- **API do WhatsApp Business (Meta/Facebook):** Toda comunicação é feita via API oficial, utilizando tokens de acesso e endpoints do Graph API para envio/recebimento de mensagens e mídias.
- **OpenAI (Whisper e TTS):** Transcrição de áudios recebidos e geração de respostas em áudio usando modelos de IA.
- **Banco de dados relacional:** Persistência de usuários, conversas, mensagens e progresso.
- **Docker:** Facilita o deploy e a escalabilidade da aplicação.
- **Armazenamento de áudios:** Respostas em áudio são geradas e servidas via endpoint próprio.
- **Ambiente seguro:** Uso de variáveis de ambiente para configuração de tokens e chaves de API.

## 🛠️ Tecnologias Utilizadas
- Python (FastAPI)
- WhatsApp Cloud API (Graph API)
- OpenAI API (Whisper, TTS)
- SQLAlchemy, Alembic
- Docker
- aiohttp, requests

## 📦 Estrutura do Projeto
- `/app` - Código principal da aplicação
- `/app/models` - Modelos do banco de dados
- `/app/services` - Lógica de negócio e integrações
- `/app/api` - Endpoints da API
- `/temp_audio` - Áudios gerados e recebidos

## ⚙️ Setup
1. Clone este repositório
2. Crie um arquivo `.env` com as variáveis:
   ```
   WHATSAPP_TOKEN=seu_token_aqui
   WHATSAPP_PHONE_NUMBER_ID=seu_id_aqui
   WHATSAPP_API_VERSION=v17.0
   OPENAI_API_KEY=sua_openai_key
   DEEPSEEK_API_KEY=sua_deepseek_key
   ```
3. Instale as dependências:
   ```
   pip install -r requirements.txt
   ```
4. Execute a aplicação:
   ```
   python main.py
   ```

## 🌐 Observações
- O token do WhatsApp deve ser gerado no Facebook Developers e pode expirar (veja a documentação oficial para renovação).
- O projeto pode ser facilmente adaptado para outros idiomas ou integrações.

## 📞 Contato
Fique à vontade para me chamar para conversar sobre integrações, automação e IA!

---

#FacebookAPI #WhatsAppAPI #Python #OpenAI #Automação #Integração #IA #Docker 