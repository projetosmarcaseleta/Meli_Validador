FROM python:3.12-slim

WORKDIR /app

# Instala curl para health check e bibliotecas nativas
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY agrupar/ ./agrupar/
RUN pip install --no-cache-dir -e .

RUN mkdir -p /app/reports /app/data

EXPOSE 8765

CMD ["uvicorn", "agrupar.web:app", "--host", "0.0.0.0", "--port", "8765"]
