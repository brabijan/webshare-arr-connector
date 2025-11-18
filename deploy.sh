#!/bin/bash
#
# Deploy script for Webshare Downloader
# Usage: ./deploy.sh [--skip-backup] [--no-build] [--clear-db]
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${APP_DIR}/backups"
DATA_DIR="${APP_DIR}/data"
DB_FILE="${DATA_DIR}/downloader.db"
MAX_BACKUPS=10
SKIP_BACKUP=false
NO_BUILD=false
CLEAR_DB=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-backup)
            SKIP_BACKUP=true
            shift
            ;;
        --no-build)
            NO_BUILD=true
            shift
            ;;
        --clear-db)
            CLEAR_DB=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Usage: $0 [--skip-backup] [--no-build] [--clear-db]"
            exit 1
            ;;
    esac
done

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running in correct directory
if [[ ! -f "${APP_DIR}/docker-compose.yml" ]]; then
    log_error "docker-compose.yml not found. Are you in the right directory?"
    exit 1
fi

log_info "Starting deployment in ${APP_DIR}"
echo ""

# Step 1: Check if Git repository
log_info "Checking Git repository status..."
if [[ ! -d "${APP_DIR}/.git" ]]; then
    log_error "Not a Git repository"
    exit 1
fi

# Check for uncommitted changes
if [[ -n $(git status -s) ]]; then
    log_warning "You have uncommitted changes:"
    git status -s
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_error "Deployment cancelled"
        exit 1
    fi
fi

# Step 2: Backup database
if [[ "$SKIP_BACKUP" == false ]]; then
    log_info "Backing up database..."
    mkdir -p "${BACKUP_DIR}"

    if [[ -f "${DB_FILE}" ]]; then
        TIMESTAMP=$(date +%Y%m%d_%H%M%S)
        BACKUP_FILE="${BACKUP_DIR}/downloader_${TIMESTAMP}.db"

        cp "${DB_FILE}" "${BACKUP_FILE}"
        log_success "Database backed up to: ${BACKUP_FILE}"

        # Compress old backup
        gzip "${BACKUP_FILE}" 2>/dev/null || true

        # Remove old backups (keep last MAX_BACKUPS)
        BACKUP_COUNT=$(ls -1 "${BACKUP_DIR}"/downloader_*.db.gz 2>/dev/null | wc -l)
        if [[ $BACKUP_COUNT -gt $MAX_BACKUPS ]]; then
            log_info "Removing old backups (keeping last ${MAX_BACKUPS})..."
            ls -1t "${BACKUP_DIR}"/downloader_*.db.gz | tail -n +$((MAX_BACKUPS + 1)) | xargs rm -f
        fi
    else
        log_warning "Database file not found, skipping backup"
    fi
else
    log_warning "Skipping database backup (--skip-backup flag)"
fi

echo ""

# Step 2.5: Clear database if requested
if [[ "$CLEAR_DB" == true ]]; then
    log_warning "Clearing database (--clear-db flag)..."

    if [[ -f "${DB_FILE}" ]]; then
        rm -f "${DB_FILE}"
        log_success "Database file deleted: ${DB_FILE}"
    else
        log_info "Database file not found, nothing to delete"
    fi
else
    log_info "Keeping existing database"
fi

echo ""

# Step 3: Pull latest changes
log_info "Pulling latest changes from Git..."
CURRENT_COMMIT=$(git rev-parse HEAD)

git fetch origin
git pull origin master

NEW_COMMIT=$(git rev-parse HEAD)

if [[ "$CURRENT_COMMIT" == "$NEW_COMMIT" ]]; then
    log_info "Already up to date (commit: ${CURRENT_COMMIT:0:7})"
else
    log_success "Updated from ${CURRENT_COMMIT:0:7} to ${NEW_COMMIT:0:7}"
    echo ""
    log_info "Changes:"
    git log --oneline ${CURRENT_COMMIT}..${NEW_COMMIT}
fi

echo ""

# Step 4: Stop running containers
log_info "Stopping running containers..."
if docker compose ps --quiet webshare-downloader &>/dev/null; then
    docker compose down
    log_success "Containers stopped"
else
    log_info "No running containers found"
fi

echo ""

# Step 5: Build new image
if [[ "$NO_BUILD" == false ]]; then
    log_info "Building new Docker image..."
    docker compose build
    log_success "Image built successfully"
else
    log_warning "Skipping Docker build (--no-build flag)"
fi

echo ""

# Step 6: Start containers
log_info "Starting containers..."
docker compose up -d
log_success "Containers started"

echo ""

# Step 7: Wait for application to be ready
log_info "Waiting for application to be ready..."
sleep 5

# Health check
MAX_RETRIES=30
RETRY_COUNT=0
HEALTH_URL="https://webshare-downloader.homelab.carpiftw.cz/api/health"

while [[ $RETRY_COUNT -lt $MAX_RETRIES ]]; do
    if curl -f -s "${HEALTH_URL}" &>/dev/null; then
        log_success "Application is healthy!"
        break
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [[ $RETRY_COUNT -eq $MAX_RETRIES ]]; then
        log_error "Health check failed after ${MAX_RETRIES} attempts"
        log_error "Check logs with: docker compose logs -f"
        exit 1
    fi

    echo -n "."
    sleep 2
done

echo ""

# Step 8: Show container status
log_info "Container status:"
docker compose ps

echo ""

# Step 9: Cleanup old Docker images (disabled to preserve build cache)
# Uncomment if you want to clean up old images:
# log_info "Cleaning up old Docker images..."
# docker image prune -f
# log_success "Cleanup complete"

echo ""

# Step 10: Show logs
log_info "Recent logs:"
docker compose logs --tail=20

echo ""
log_success "Deployment completed successfully!"
echo ""
log_info "Application is running at:"
echo "  - Local: http://localhost:5050"
echo "  - Public: https://webshare-downloader.homelab.carpiftw.cz"
echo ""
log_info "Useful commands:"
echo "  - View logs: docker compose logs -f"
echo "  - Restart: docker compose restart"
echo "  - Stop: docker compose down"
echo "  - Database backup: ls -lh ${BACKUP_DIR}"
echo ""
