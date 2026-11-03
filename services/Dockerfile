# Image commune à tous les services ShopFlow : python slim, utilisateur non root, CMD en forme exec.
# Construite avec --build-arg SERVICE=<gateway|orders|inventory|payment|bank>
FROM python:3.12-slim
ARG SERVICE
ENV PYTHONUNBUFFERED=1 SERVICE_NAME=${SERVICE}
RUN useradd --create-home appuser
WORKDIR /app
COPY common/ ./common/
COPY ${SERVICE}/app.py ./app.py
USER appuser
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:%s/health/live' % os.environ['PORT'], timeout=2)"
CMD ["python", "app.py"]
