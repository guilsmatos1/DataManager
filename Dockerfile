FROM python:3.12-slim
WORKDIR /app

# Instalar dependências de sistema comumente necessárias para o openbb / pandas
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Comando padrão
CMD ["python", "main.py", "-i"]
