FROM python:3.12-slim

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt

COPY app ./app
COPY static ./static
COPY templates ./templates

RUN groupadd --gid "${APP_GID}" amp-dashboard \
    && useradd --uid "${APP_UID}" --gid amp-dashboard --no-create-home \
        --home-dir /app --shell /usr/sbin/nologin amp-dashboard

USER amp-dashboard

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
