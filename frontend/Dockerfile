# Stage 1: build the React app.
FROM node:20-alpine AS builder

WORKDIR /app

# Install deps before copying source so this layer caches across code changes.
COPY package*.json .
RUN npm ci

COPY . .

# docker-compose passes VITE_BACKEND_URL=http://localhost:8000 at build time.
# Why at build time (ARG/ENV): Vite bakes env vars into the JS bundle —
# they are NOT available at runtime like server-side env vars.
ARG VITE_BACKEND_URL=http://localhost:8000
ENV VITE_BACKEND_URL=$VITE_BACKEND_URL
RUN npm run build


# Stage 2: serve the static output with nginx.
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
