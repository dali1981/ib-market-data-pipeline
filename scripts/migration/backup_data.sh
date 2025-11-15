#!/bin/bash
#
# Backup dlt-ibapi data directory before migration
#
# Usage:
#   ./scripts/migration/backup_data.sh                    # Backup to ./data_backup_{timestamp}
#   ./scripts/migration/backup_data.sh /path/to/backup    # Backup to specific location
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SOURCE_DIR="./data"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DEFAULT_BACKUP_DIR="./data_backup_${TIMESTAMP}"
BACKUP_DIR="${1:-$DEFAULT_BACKUP_DIR}"

echo -e "${GREEN}=== dlt-ibapi Data Backup ===${NC}\n"

# Check if source exists
if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}❌ Error: Source directory not found: $SOURCE_DIR${NC}"
    exit 1
fi

# Calculate source size
SOURCE_SIZE=$(du -sh "$SOURCE_DIR" 2>/dev/null | cut -f1)
FILE_COUNT=$(find "$SOURCE_DIR" -type f | wc -l)

echo "Source:      $SOURCE_DIR"
echo "Destination: $BACKUP_DIR"
echo "Size:        $SOURCE_SIZE"
echo "Files:       $FILE_COUNT"
echo ""

# Confirm backup
read -p "Proceed with backup? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Backup cancelled"
    exit 0
fi

echo -e "\n${YELLOW}Backing up data...${NC}\n"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Copy data with progress
rsync -av --progress "$SOURCE_DIR/" "$BACKUP_DIR/"

# Verify backup
BACKUP_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
BACKUP_FILE_COUNT=$(find "$BACKUP_DIR" -type f | wc -l)

echo -e "\n${GREEN}=== Backup Complete ===${NC}\n"
echo "Backup location: $BACKUP_DIR"
echo "Backup size:     $BACKUP_SIZE"
echo "Files backed up: $BACKUP_FILE_COUNT"

# Create manifest file
MANIFEST="${BACKUP_DIR}/BACKUP_MANIFEST.txt"
cat > "$MANIFEST" <<EOF
dlt-ibapi Data Backup Manifest
==============================

Backup Date:    $(date)
Source:         $SOURCE_DIR
Destination:    $BACKUP_DIR
Source Size:    $SOURCE_SIZE
Files Backed up: $BACKUP_FILE_COUNT

Datasets:
$(find "$BACKUP_DIR" -maxdepth 1 -type d ! -name ".*" ! -name "$(basename $BACKUP_DIR)" | sed 's/^/  - /')

To restore:
  rm -rf $SOURCE_DIR
  cp -r $BACKUP_DIR $SOURCE_DIR

To verify:
  diff -r $SOURCE_DIR $BACKUP_DIR
EOF

echo -e "\n${GREEN}✓ Manifest created: $MANIFEST${NC}"
echo -e "\n${GREEN}Backup successful!${NC}"
