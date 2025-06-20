# Use an official lightweight Python image.
FROM python:3.13

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file to the working directory
COPY requirements.txt .

# Install any dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Run the web server on container startup using Gunicorn
# Gunicorn is a robust WSGI HTTP server for UNIX.
# Cloud Run will set the PORT environment variable for you.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
