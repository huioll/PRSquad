FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY prsquad ./prsquad

RUN pip install --no-cache-dir .

EXPOSE 8001
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "prsquad.main:app", "--host", "0.0.0.0", "--port", "8001"]
