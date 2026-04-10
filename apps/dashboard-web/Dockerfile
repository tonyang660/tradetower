FROM node:24-alpine AS build

WORKDIR /app

ARG VITE_DASHBOARD_API_BASE_URL
ENV VITE_DASHBOARD_API_BASE_URL=$VITE_DASHBOARD_API_BASE_URL

COPY apps/dashboard-web/package*.json ./
RUN npm install

COPY apps/dashboard-web ./
RUN npm run build

FROM nginx:alpine

COPY apps/dashboard-web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]