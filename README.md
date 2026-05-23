# Step -0 :: stop containers
docker-compose down 

# step-1:: For removing images/containber
docker system prune -a --volumes -f

# Step-2 :: build
docker-compose up --build -d
# Step-3 :: check status 
docker-compose ps

# Check logs any time::
docker-compose logs -f api
docker-compose logs -f db


# Tag  Image


# Step 2: Tag the API image
docker tag orion_module_api:latest orion_module_api:v1.0.0
docker tag orion_module_api:v1.0.0 gopalorion/orion_module_api:v1.0.0
docker tag orion_module_api:latest gopalorion/orion_module_api:latest

# Step 3: Tag the DB image
docker tag orion_db_mysql:latest gopalorion/orion_db_mysql:v1.0.0
docker tag orion_db_mysql:latest gopalorion/orion_db_mysql:latest

# Step 4: Push to Docker Hub
docker push gopalorion/orion_module_api:v1.0.0
docker push gopalorion/orion_module_api:latest
docker push gopalorion/orion_db_mysql:v1.0.0
docker push gopalorion/orion_db_mysql:latest


# on another computer.
# pull the image:
docker pull gopalorion/orion_module_api:v1.0.0
docker pull gopalorion/orion_db_mysql:v1.0.0

docker-compose -f docker-compose.prod.yml up -d







Submit API -> Controller -> Service (DB save) -> Pipeline -> Engines -> Aggregator -> DB (analysis_json) -> Response