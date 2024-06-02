FROM python:3.9-slim

# Install necessary system dependencies
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libpoppler-cpp-dev \
    python3-pip \
    python3-dev \
    build-essential \
    && apt-get clean

# Install Python packages
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Set the working directory
WORKDIR /app

# Copy the script and other necessary files into the container
COPY . /app

# Define the command to run the script
CMD ["python", "process_pdfs.py"]
