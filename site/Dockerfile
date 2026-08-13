# Serves the VeritX front-facing site (site/) behind nginx.
# Build:  docker build -t veritx-site -f site/Dockerfile .
# Run:    docker run -p 8080:80 veritx-site
FROM nginx:1.27-alpine
COPY site/ /usr/share/nginx/html/
