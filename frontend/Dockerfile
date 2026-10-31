# frontend-Image (P3.6, docs/architecture/frontend.md): Angular-Build, ausgeliefert von nginx
# ohne root. Gebaut nur in der CI (ADR-0008): Node laeuft nie auf der NAS, die NAS zieht das
# fertige Image aus GHCR. Lokal: make local-ui.
FROM node:24.22.2-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30.6-alpine
LABEL org.opencontainers.image.source="https://github.com/KaczmarekD/AktienAnalyse"
LABEL org.opencontainers.image.description="Value-Analyzer: Web-UI (Angular) hinter nginx"
# Hostnamen, unter denen das UI aufgerufen wird; alle anderen bekommen keine Antwort.
# Auf der NAS setzt docker-compose.yml den Wert aus UI_SERVER_NAMES.
ENV VA_SERVER_NAMES="localhost 127.0.0.1"
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist/va-frontend/browser /usr/share/nginx/html
EXPOSE 8080
