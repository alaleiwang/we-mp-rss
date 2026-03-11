
FROM node:20.18.3-bookworm-slim AS frontend-builder

WORKDIR /app/web_ui
COPY web_ui/package.json web_ui/package-lock.json ./
RUN npm install
COPY web_ui/ ./
RUN npm run build

FROM --platform=$BUILDPLATFORM ghcr.io/rachelos/base-full:latest AS runtime

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV INSTALL=True
ENV BROWSER_TYPE=webkit
ENV PLANT_PATH=/app/env

WORKDIR /app
COPY requirements.txt install.sh ./
RUN chmod +x /app/install.sh && /app/install.sh

COPY . .
COPY config.example.yaml /app/config.yaml
COPY --from=frontend-builder /app/web_ui/dist/ /tmp/web_ui_dist/
RUN rm -rf /app/static/* \
    && cp -r /tmp/web_ui_dist/* /app/static/ \
    && chmod +x /app/start.sh

EXPOSE 8001
CMD ["/app/start.sh"]
