# The dashboard's web server with its pages inside (the published "web" image). Build from the repository root.
FROM nginx:1.31.8-alpine
COPY stack/landing/nginx.conf /etc/nginx/conf.d/default.conf
COPY stack/landing/site /usr/share/nginx/html
COPY modules /usr/share/modules
