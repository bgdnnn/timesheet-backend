FROM node:20-slim

WORKDIR /app
RUN apt-get update && apt-get install -y ca-certificates \
	&& rm -rf /var/lib/apt/lists/*
COPY package*.json ./
RUN npm ci 

COPY . .
RUN npx prisma generate

EXPOSE 4000
CMD ["node", "src/server.js"]