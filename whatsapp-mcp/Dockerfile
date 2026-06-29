# Use official Golang image to get the newest Go version
FROM golang:latest

# Avoid tzdata interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies (Python3, Pip, FFmpeg)
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set Working directory
WORKDIR /app

# Copy all files into container
COPY . .

# Install Python requirements globally in container
RUN pip3 install -r requirements.txt --break-system-packages

# Build the Go Bridge
WORKDIR /app/whatsapp-bridge
RUN go build -o bridge main.go

# Return to root directory
WORKDIR /app

# Make the start script executable
RUN chmod +x start.sh

# Run the unified start script
CMD ["./start.sh"]
