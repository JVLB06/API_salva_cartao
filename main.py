# Importação de bibliotecas essenciais
from fastapi import FastAPI
from fastapi.responses import JSONResponse, HTMLResponse
import jwt
from datetime import datetime, timedelta, timezone
from cachetools import TTLCache
from pydantic import BaseModel
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from logging.handlers import TimedRotatingFileHandler
import os

# Declaração de variáveis
# Configuração do servidor de email
servidor_smtp = 'smtp.gmail.com'
porta = 587 # TLS
usuario = 'butzenjvlb@gmail.com'
senha = 'qanp zpjf cixf lydf'

app = FastAPI()
SECRET_KEY = "chave"
data_inicial = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S")

# Cache para tokens pendentes e válidos
tokens_pendentes = TTLCache(maxsize=1000, ttl=18000)  # 5h
tokens_validos = TTLCache(maxsize=1000, ttl=36000)    # 10h

# Modelos de entrada de dados
class DadosCartao(BaseModel):
    cod_cartao: str
    nome_cartao: str
    validade: str
    cvv: int
    valor: float
    parcelas: int
class DadosEmail(BaseModel):
    email: str

# Função para censurar os dados do cartão
def mascarar_string(s, visiveis=4):
    return "*" * (len(s) - visiveis) + s[-visiveis:]
# Gerador de log diário
def configurar_logger():
    # Cria a pasta 'logs' se não existir
    if not os.path.exists("logs"):
        os.makedirs("logs")
    handler = TimedRotatingFileHandler(
        filename="logs/log.txt",      # Sempre escreve nesse, mas rotaciona
        when="midnight",              # Rotaciona à meia-noite
        interval=1,                   # A cada 1 dia
        backupCount=30,                # Mantém os últimos 30 arquivos
        encoding="utf-8"
    )
    # Nome do arquivo com data no formato DD.MM.txt
    handler.suffix = "%d.%m"
    # Configuração do logger
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            handler,
            logging.StreamHandler()  # Para mostrar no console também
        ]
    )
    logging.info("API iniciada! Bom dia!")
    logging.info(f"Operante desde: {data_inicial}")

# Chama a função na inicialização da API
configurar_logger()

# Solicitação de compra por parte da bandeira de cartão
@app.post("/solicita_compra")
def solicita_compra(dados_cartao: DadosCartao):
    """
    Gera um token JWT a partir dos dados do cartão e salva no cache de pendentes.
    """
    payload = dados_cartao.dict() 
    payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=5) # 5h até expirar
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    logging.info(f"Solicitação de compra recebida: {token}")
    payload["exp"] =  f"{payload['exp']}" # Converte para string ISO
    # Salva no cache de tokens pendentes
    tokens_pendentes[token] = {
        "dados": payload,
        "status": "aguardando",
        "email": None
    }
    return {"token": token}

# Acesso aos tokens pendentes para validação do banco
@app.get("/tokens_pendentes")
def get_tokens_pendentes():
    """
    Retorna os tokens pendentes armazenados no cache.
    """
    resposta = []
    # Itera sobre os tokens pendentes e adiciona eles à resposta
    for token, payload in tokens_pendentes.items():
        if not isinstance(payload, dict):
            continue  # Garante que o payload seja um dicionário
        payload["token"] = token
        resposta.append(payload)
    if resposta == []:
        logging.info("Nenhum token pendente encontrado.")
    else:
        logging.info(f"Tokens pendentes encontrados: {len(resposta)}")
    return JSONResponse(content=resposta)

# Endpoint para obter o email do usuário
@app.post("/obter_email/{token}")
def obter_email(token: str, dados_email: DadosEmail):
    """
    Recebe um token JWT e adiciona o email no cache. Depois realiza o envio do email em questão
    """
    # Gera erro se o token não for encontrado ou estiver expirado
    if token not in tokens_pendentes:
        logging.error(f"Token não encontrado ou expirado: {token}")
        return {"mensagem": "Token não encontrado ou expirado."}
    tokens_pendentes[token]["email"] = dados_email.email # Adiciona o email ao cache
    logging.info(f"Email recebido: {dados_email.email} para o token: {token}")
    try:
        # Organiza o servidor dos emails
        servidor = smtplib.SMTP(servidor_smtp, porta)
        servidor.starttls()  # Inicia a criptografia TLS
        servidor.login(usuario, senha)
        logging.info("Servidor de email conectado com sucesso!")
        # Envio do email
        # Criar a mensagem de e-mail personalizada
        mensagem = MIMEMultipart()
        mensagem["Subject"] = "No-reply - Token de compra"
        mensagem["From"] = usuario
        mensagem["To"] = dados_email.email
        corpo_email = f"""
    <html>
        <head>
            <title>Confirmação de Compra</title>  
            <link rel="stylesheet" href="mail.css">
        </head>
        <body>
            <div class="titulo">
                <h1>Uma compra foi efetuada em seu nome</h1>
                <p><span class="informaçoes">Nome:</span> {mascarar_string(tokens_pendentes[token]["nome_cartao"], 4)}</p>
                <p><span class="informaçoes">Número do cartão:</span> {mascarar_string(tokens_pendentes[token]["cod_cartao"]), 1}</p>
                <p><span class="informaçoes">Vencimento:</span> {tokens_pendentes[token]["validade"]}</p>
                <p><span class="informaçoes">CVV:</span> {tokens_pendentes[token]["validade"]}</p>
                <p><span class="informaçoes">Valor:</span> R$ {tokens_pendentes[token]["valor"]}</p>
                <p><span class="informaçoes">Quantidade de Parcelas:</span> {tokens_pendentes[token]["parcelas"]}x</p>
                <div class="importante">
                    <p style="flex: 1; min-width: 200px;">Para confirmar sua compra de forma segura, clique no botão</p>
                    <a href="http://localhost:5000/valida_compra/{token}" class="botao">Confirmar Compra</a>
                </div>
                <p class="final">Caso não reconheça esta compra, apenas ignore este email.</p>
            </div>
            <script>
                console.log();
            </script>
        </body>

    </html>
    """
        # Anexar corpo do e-mail
        mensagem.attach(MIMEText(corpo_email, "html"))

        # Enviar o e-mail
        servidor.sendmail(usuario, dados_email.email, mensagem.as_string())
        logging.info(f"E-mail enviado para: {dados_email.email}")
        servidor.quit()
        logging.info("Servidor de email desconectado!")
    except Exception as e:
        logging.error(f"Erro ao enviar o e-mail: {str(e)}")
        return {"mensagem": "Erro ao enviar o e-mail."}
    return {"mensagem": "Email registrado com sucesso!"}


@app.get("/valida_compra/{token}")
def valida_compra(token: str):
    """
    Simula a validação da compra pelo usuário ao clicar no link.
    Move o token para o cache de tokens válidos.
    """
    if token not in tokens_pendentes:
        logging.error(f"Token não encontrado ou expirado: {token}")
        return HTMLResponse(content="<h1>Token não encontrado ou expirado.</h1>",status_code=404)

    dados_token = tokens_pendentes[token]["dados"]
    
    # Gera um novo token válido com mais tempo
    novo_payload = {
        **dados_token,
        "status": "confirmado",
        "exp": datetime.now(timezone.utc) + timedelta(hours=10)
    }
    novo_token = jwt.encode(novo_payload, SECRET_KEY, algorithm="HS256")
    logging.info(f"Token de confirmação gerado: {novo_token}")
    novo_payload["exp"] = f"{novo_payload['exp']}"  # Converte para string ISO
    tokens_validos[novo_token] = {
        "dados": novo_payload,
        "email": tokens_pendentes[token]["email"]
    }

    # Remove o antigo
    del tokens_pendentes[token]
    logging.info(f"Token movido para tokens válidos: {novo_token}")
    with open("confirma.html", "r") as file:
        html_content = file.read()
    logging.info("Compra confirmada com sucesso! Status: 200")
    return HTMLResponse(content=html_content, status_code=200)


@app.get("/tokens_validos")
def get_tokens_validos():
    """
    Retorna os tokens válidos armazenados no cache.
    """
    logging.info(f"Tokens válidos encontrados: {len(tokens_validos)}")
    return JSONResponse([
        {"token": k, **v} for k, v in tokens_validos.items()
    ])
