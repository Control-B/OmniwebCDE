FROM node:22.21.1-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
ARG VITE_API_URL
ARG VITE_OIDC_ISSUER
ENV VITE_API_URL=$VITE_API_URL VITE_OIDC_ISSUER=$VITE_OIDC_ISSUER
COPY . .
RUN npm run build

FROM node:22.21.1-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build /app/.output ./.output
USER node
EXPOSE 3000
CMD ["node", ".output/server/index.mjs"]
