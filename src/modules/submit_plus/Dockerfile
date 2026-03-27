# Use an official Python runtime as a parent image
FROM python:3.11-slim

WORKDIR /app
COPY . /app
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi
EXPOSE 8000
CMD ["python", "-m", "src.modules.submit_plus"]
