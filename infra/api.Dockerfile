FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv/mioagent
COPY pyproject.toml README.md ./
COPY mio ./mio
RUN pip install --no-cache-dir .
RUN useradd -m -u 10001 mio
USER mio
EXPOSE 8000
CMD ["uvicorn", "mio.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
