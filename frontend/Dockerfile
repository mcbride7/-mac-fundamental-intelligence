FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_API_TOKEN=
# Railway passes the GitHub commit being deployed; shown at the bottom of the menu as "Version"
ARG RAILWAY_GIT_COMMIT_SHA=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_PUBLIC_API_TOKEN=$NEXT_PUBLIC_API_TOKEN NEXT_PUBLIC_BUILD=$RAILWAY_GIT_COMMIT_SHA
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
