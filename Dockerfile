FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
# Versões e hashes travados: o que roda na VPS é exatamente o que foi testado.
RUN pip install --no-deps --require-hashes -r requirements.txt
COPY app.py config.py evolution.py loja.py mensagem.py painel_html.py ./

RUN useradd --uid 10001 --create-home canal && mkdir -p /data && chown canal:canal /data
USER canal
VOLUME /data

EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/saude', timeout=4)"

# Sem log de acesso: endereço e horário de cada leitura não precisam ficar registrados.
CMD ["uvicorn", "app:fabrica", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-server-header"]
