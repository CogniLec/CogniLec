# Production build of the client PWA, served by nginx.
#
# VITE_API_BASE_URL is a BUILD-time value (Vite bakes import.meta.env.*
# into the compiled JS), not a runtime env var -- unlike every other
# service in docker-compose.yml, changing it means rebuilding this image,
# not just restarting the container. Pass it via `build.args` in
# docker-compose.yml (VITE_API_BASE_URL env var, default below matches
# this deployment's actual API address as of writing).
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL=http://localhost:8123
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
