FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY urja_api ./urja_api
RUN useradd --create-home urja
USER urja
EXPOSE 8000
CMD ["uvicorn", "urja_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
