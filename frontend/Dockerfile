# --- CEMA cUAS Frontend image ---
FROM node:20-alpine AS build

WORKDIR /app

# Install deps first for better layer caching
COPY package.json yarn.lock* ./
RUN corepack enable && yarn install --frozen-lockfile || yarn install

COPY . .

# REACT_APP_BACKEND_URL is baked in at build time. Pass it as a build arg.
ARG REACT_APP_BACKEND_URL=http://localhost:8001
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL

RUN yarn build

# --- Serve stage ---
FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
