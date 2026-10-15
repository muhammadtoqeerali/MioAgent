FROM node:22-alpine AS build
WORKDIR /dashboard
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi
COPY . .
RUN npm run build

FROM node:22-alpine
ENV NODE_ENV=production
WORKDIR /dashboard
COPY --from=build /dashboard ./
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
