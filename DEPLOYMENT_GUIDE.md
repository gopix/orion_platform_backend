# Orion Module API - Deployment Guide for Another System

## Step 1: Pull the Docker Image

```powershell
docker login -u gopalorion
# Enter PAT when prompted

docker pull gopalorion/orion_module_api:v1.0.0
```

## Step 2: Option A - Using Docker Compose (Recommended)

Copy this `docker-compose.yml` to your system:

```yaml
services:
  api:
    image: gopalorion/orion_module_api:v1.0.0
    container_name: orion_module_api
    ports:
      - "8000:8000"
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      DB_HOST: db
      DB_PORT: 3306
      DB_USER: root
      DB_PASSWORD: root
      DB_NAME: orion_db
      UPLOAD_DIR: /app/uploads
      MAX_UPLOAD_SIZE: 104857600
      ALLOWED_MIME_TYPES: application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain
      STORAGE_PROVIDER: local
      LOG_DIR: /app/logs
      LOG_LEVEL: INFO

  db:
    image: mysql:8.0
    container_name: orion_db_mysql
    restart: always
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: orion_db
    ports:
      - "3306:3306"
    volumes:
      - orion_db_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-uroot", "-proot"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  orion_db_data:
```

Then run:

```powershell
docker-compose up -d
docker-compose ps
```

## Step 2: Option B - Using Docker Run (If no docker-compose)

```powershell
# Start MySQL container first
docker run -d \
  --name orion_db_mysql \
  -e MYSQL_ROOT_PASSWORD=root \
  -e MYSQL_DATABASE=orion_db \
  -p 3306:3306 \
  mysql:8.0

# Wait 10 seconds for MySQL to be ready
Start-Sleep -Seconds 10

# Run the API container
docker run -d -p 8000:8000 \
  -e DB_HOST=host.docker.internal \
  -e DB_PORT=3306 \
  -e DB_USER=root \
  -e DB_PASSWORD=root \
  -e DB_NAME=orion_db \
  -e UPLOAD_DIR=/app/uploads \
  -e MAX_UPLOAD_SIZE=104857600 \
  -e ALLOWED_MIME_TYPES=application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain \
  -e STORAGE_PROVIDER=local \
  -e LOG_DIR=/app/logs \
  -e LOG_LEVEL=INFO \
  --name orion_module_api \
  --link orion_db_mysql:db \
  gopalorion/orion_module_api:v1.0.0
```

## Step 3: Access the API

Open your browser:
```
http://localhost:8000/docs
```

## Step 4: Check Logs

```powershell
# If using docker-compose
docker-compose logs -f api

# If using docker run
docker logs orion_module_api
```

## Environment Variables Explained

| Variable | Default | Purpose |
|----------|---------|---------|
| DB_HOST | localhost | Database host (use `db` if using docker-compose, `host.docker.internal` for Docker Desktop) |
| DB_PORT | 3306 | MySQL port |
| DB_USER | root | Database user |
| DB_PASSWORD | root | Database password |
| DB_NAME | orion_db | Database name |
| UPLOAD_DIR | /app/uploads | Directory for file uploads inside container |
| MAX_UPLOAD_SIZE | 104857600 | Maximum upload size in bytes (100MB) |
| ALLOWED_MIME_TYPES | PDF, Word, Text | Allowed file types |
| STORAGE_PROVIDER | local | Storage type (local or s3) |
| LOG_DIR | /app/logs | Log directory inside container |
| LOG_LEVEL | INFO | Logging level |

## Troubleshooting

**Container crashes immediately?**
- Check logs: `docker logs orion_module_api`
- Ensure all 11 environment variables are set
- Wait for MySQL to be healthy before API starts

**Can't connect to database?**
- If both containers: Use `DB_HOST: db` (service name)
- If separate systems: Use actual IP address or hostname
- Check MySQL is running: `docker ps`

**Port 8000 already in use?**
```powershell
docker run -d -p 9000:8000 ...  # Use port 9000 instead
```

**Port 3306 already in use?**
```powershell
docker run -d -p 3307:3306 ...  # Use port 3307 instead
```
