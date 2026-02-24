FROM node:22-alpine

WORKDIR /app

RUN apk add --no-cache chromium nss freetype harfbuzz ca-certificates ttf-freefont

COPY package.json ./
RUN npm install --omit=dev

COPY src ./src

EXPOSE 8081
ENV CHROME_PATH=/usr/bin/chromium
CMD ["npm", "start"]
