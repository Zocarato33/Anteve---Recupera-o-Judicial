FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV ANTEVE_DB=/app/data/anteve.db
EXPOSE 8000
CMD ["python", "-m", "anteve.cli", "servir", "--porta", "8000"]
