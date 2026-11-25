# Sandbox image: runs AI-written world models. Standard library only, no secrets.
FROM python:3.12-alpine
WORKDIR /sandbox
COPY runner.py serve.py /sandbox/
USER 65534:65534
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Default: one world per container, protocol on stdin/stdout.
# docker compose overrides this with serve.py (one process per connection).
CMD ["python", "-I", "-u", "/sandbox/runner.py"]
