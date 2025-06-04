#!/bin/bash
# Meta-Agent Deployment Script
# This script deploys the Meta-Agent application to either a local environment or Google Cloud Platform.

set -e  # Exit immediately if a command exits with a non-zero status

# Default values
DEPLOY_ENV="local"  # Options: local, gcp
CONFIG_FILE=".env"
PORT=8000
GCP_PROJECT=""
GCP_REGION="us-central1"
USE_DOCKER=true
DOCKER_TAG="meta-agent:latest"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print usage information
function print_usage() {
    echo -e "${BLUE}Meta-Agent Deployment Script${NC}"
    echo ""
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  -e, --env ENV         Deployment environment (local, gcp) [default: local]"
    echo "  -c, --config FILE     Configuration file path [default: .env]"
    echo "  -p, --port PORT       Port to run the application on [default: 8000]"
    echo "  --gcp-project ID      Google Cloud project ID (required for GCP deployment)"
    echo "  --gcp-region REGION   Google Cloud region [default: us-central1]"
    echo "  --no-docker           Run without Docker (local deployment only)"
    echo "  -h, --help            Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 --env local                    # Deploy locally using Docker"
    echo "  $0 --env local --no-docker        # Deploy locally without Docker"
    echo "  $0 --env gcp --gcp-project my-project  # Deploy to Google Cloud Run"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
        -e|--env)
            DEPLOY_ENV="$2"
            shift 2
            ;;
        -c|--config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        --gcp-project)
            GCP_PROJECT="$2"
            shift 2
            ;;
        --gcp-region)
            GCP_REGION="$2"
            shift 2
            ;;
        --no-docker)
            USE_DOCKER=false
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            print_usage
            exit 1
            ;;
    esac
done

# Validate environment
if [[ ! "$DEPLOY_ENV" =~ ^(local|gcp)$ ]]; then
    echo -e "${RED}Error: Invalid environment. Must be 'local' or 'gcp'.${NC}"
    exit 1
fi

# Validate GCP project for GCP deployment
if [[ "$DEPLOY_ENV" == "gcp" && -z "$GCP_PROJECT" ]]; then
    echo -e "${RED}Error: GCP project ID is required for GCP deployment.${NC}"
    echo "Use --gcp-project to specify the project ID."
    exit 1
fi

# Check if config file exists
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo -e "${YELLOW}Warning: Config file '$CONFIG_FILE' not found.${NC}"
    
    if [[ "$DEPLOY_ENV" == "local" ]]; then
        echo -e "Creating a default .env file..."
        cat > .env << EOF
# Meta-Agent Environment Configuration
META_AGENT_ENVIRONMENT=development
META_AGENT_DEBUG_MODE=true
META_AGENT_LOG_LEVEL=DEBUG

# LLM Provider Configuration
# Uncomment and set one of the following API keys based on your provider
# META_AGENT_LLM_PROVIDER=openai
# META_AGENT_LLM_API_KEY=your_openai_api_key
# META_AGENT_LLM_MODEL=gpt-4

# META_AGENT_LLM_PROVIDER=anthropic
# META_AGENT_LLM_API_KEY=your_anthropic_api_key
# META_AGENT_LLM_MODEL=claude-2

# META_AGENT_LLM_PROVIDER=google
# META_AGENT_LLM_API_KEY=your_google_api_key
# META_AGENT_LLM_MODEL=gemini-pro

# Database Configuration
META_AGENT_DB_TYPE=sqlite
META_AGENT_DB_CONNECTION_STRING=sqlite:///./data/meta_agent.db

# Server Configuration
META_AGENT_HOST=0.0.0.0
META_AGENT_PORT=8000
META_AGENT_WORKERS=1

# Connector Configuration
# META_AGENT_SLACK_API_TOKEN=your_slack_api_token
# META_AGENT_SLACK_SIGNING_SECRET=your_slack_signing_secret
# META_AGENT_JIRA_URL=your_jira_url
# META_AGENT_JIRA_USERNAME=your_jira_username
# META_AGENT_JIRA_API_TOKEN=your_jira_api_token
EOF
        echo -e "${GREEN}Created default .env file. Please edit it with your API keys.${NC}"
    fi
fi

# Function to check if a command exists
function command_exists() {
    command -v "$1" &> /dev/null
}

# Function to deploy locally
function deploy_local() {
    echo -e "${BLUE}Deploying Meta-Agent locally...${NC}"
    
    # Create data directory if it doesn't exist
    mkdir -p data
    
    if [[ "$USE_DOCKER" == true ]]; then
        echo -e "${BLUE}Using Docker for deployment...${NC}"
        
        # Check if Docker is installed
        if ! command_exists docker; then
            echo -e "${RED}Error: Docker is not installed. Please install Docker or use --no-docker option.${NC}"
            exit 1
        fi
        
        # Build Docker image
        echo -e "${BLUE}Building Docker image...${NC}"
        docker build -t "$DOCKER_TAG" .
        
        # Run Docker container
        echo -e "${BLUE}Starting Docker container...${NC}"
        docker run -d \
            --name meta-agent \
            -p "$PORT:8000" \
            --env-file "$CONFIG_FILE" \
            -v "$(pwd)/data:/app/data" \
            "$DOCKER_TAG"
        
        echo -e "${GREEN}Meta-Agent is now running in Docker on port $PORT${NC}"
        echo -e "You can access it at: http://localhost:$PORT"
        echo -e "To stop it, run: docker stop meta-agent && docker rm meta-agent"
    else
        echo -e "${BLUE}Deploying without Docker...${NC}"
        
        # Check if Python is installed
        if ! command_exists python3; then
            echo -e "${RED}Error: Python 3 is not installed.${NC}"
            exit 1
        fi
        
        # Create virtual environment if it doesn't exist
        if [[ ! -d "venv" ]]; then
            echo -e "${BLUE}Creating virtual environment...${NC}"
            python3 -m venv venv
        fi
        
        # Activate virtual environment
        echo -e "${BLUE}Activating virtual environment...${NC}"
        source venv/bin/activate
        
        # Install dependencies
        echo -e "${BLUE}Installing dependencies...${NC}"
        pip install -r requirements.txt
        
        # Load environment variables
        if [[ -f "$CONFIG_FILE" ]]; then
            echo -e "${BLUE}Loading environment variables from $CONFIG_FILE...${NC}"
            set -o allexport
            source "$CONFIG_FILE"
            set +o allexport
        fi
        
        # Start the application
        echo -e "${BLUE}Starting Meta-Agent...${NC}"
        uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload &
        
        echo -e "${GREEN}Meta-Agent is now running on port $PORT${NC}"
        echo -e "You can access it at: http://localhost:$PORT"
        echo -e "To stop it, find the process ID and use 'kill <PID>'"
    fi
}

# Function to deploy to GCP
function deploy_gcp() {
    echo -e "${BLUE}Deploying Meta-Agent to Google Cloud Platform...${NC}"
    
    # Check if gcloud CLI is installed
    if ! command_exists gcloud; then
        echo -e "${RED}Error: Google Cloud SDK (gcloud) is not installed.${NC}"
        echo "Please install it from: https://cloud.google.com/sdk/docs/install"
        exit 1
    fi
    
    # Check if user is logged in to gcloud
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" &> /dev/null; then
        echo -e "${YELLOW}You need to log in to Google Cloud.${NC}"
        gcloud auth login
    fi
    
    # Set the GCP project
    echo -e "${BLUE}Setting GCP project to $GCP_PROJECT...${NC}"
    gcloud config set project "$GCP_PROJECT"
    
    # Build and push Docker image to Google Container Registry
    echo -e "${BLUE}Building and pushing Docker image to Google Container Registry...${NC}"
    IMAGE_NAME="gcr.io/$GCP_PROJECT/meta-agent:latest"
    
    # Build the Docker image
    docker build -t "$IMAGE_NAME" .
    
    # Configure Docker to use gcloud as a credential helper
    gcloud auth configure-docker
    
    # Push the image to Google Container Registry
    docker push "$IMAGE_NAME"
    
    # Deploy to Cloud Run
    echo -e "${BLUE}Deploying to Cloud Run...${NC}"
    gcloud run deploy meta-agent \
        --image="$IMAGE_NAME" \
        --platform=managed \
        --region="$GCP_REGION" \
        --allow-unauthenticated \
        --env-vars-file="$CONFIG_FILE" \
        --memory=1Gi
    
    # Get the deployed URL
    SERVICE_URL=$(gcloud run services describe meta-agent --platform=managed --region="$GCP_REGION" --format='value(status.url)')
    
    echo -e "${GREEN}Meta-Agent has been deployed to Cloud Run!${NC}"
    echo -e "You can access it at: $SERVICE_URL"
}

# Main deployment logic
echo -e "${BLUE}Starting Meta-Agent deployment...${NC}"
echo -e "Environment: $DEPLOY_ENV"
echo -e "Config file: $CONFIG_FILE"

# Deploy based on selected environment
if [[ "$DEPLOY_ENV" == "local" ]]; then
    deploy_local
elif [[ "$DEPLOY_ENV" == "gcp" ]]; then
    deploy_gcp
fi

echo -e "${GREEN}Deployment completed successfully!${NC}"
