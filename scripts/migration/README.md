# Migration Scripts

Tools for migrating existing Parquet data to Delta Lake format.

## Contents

- **`migrate_to_delta.py`** - Python CLI tool for migrating Parquet to Delta Lake
- **`backup_data.sh`** - Bash script for backing up data before migration

## Quick Start

### 1. Backup Your Data (Recommended)

```bash
# Backup to default location (./data_backup_{timestamp})
./scripts/migration/backup_data.sh

# Or specify custom backup location
./scripts/migration/backup_data.sh /path/to/backup
```

### 2. Preview Migration (Dry Run)

```bash
# Preview what would be migrated
uv run python scripts/migration/migrate_to_delta.py migrate --all --dry-run

# Or preview specific dataset
uv run python scripts/migration/migrate_to_delta.py migrate --dataset stocks --dry-run
```

### 3. Run Migration

```bash
# Migrate all datasets to default location (./data_delta)
uv run python scripts/migration/migrate_to_delta.py migrate --all

# Migrate to custom location
uv run python scripts/migration/migrate_to_delta.py migrate --all --output ./my_delta_data

# Migrate to S3/MinIO
uv run python scripts/migration/migrate_to_delta.py migrate --all --output s3://ibapi-data/warehouse
```

### 4. Verify Migration

```bash
# Verify specific table
uv run python scripts/migration/migrate_to_delta.py verify stocks historical_bars

# With custom paths
uv run python scripts/migration/migrate_to_delta.py verify stocks historical_bars \
    --delta-path ./data_delta \
    --parquet-path ./data
```

## Migration Tool (migrate_to_delta.py)

### Commands

#### `migrate`

Migrate Parquet data to Delta Lake format.

**Options:**
- `--dataset, -d` - Migrate specific dataset (e.g., stocks, options)
- `--all, -a` - Migrate all datasets
- `--source, -s` - Source data directory (default: ./data)
- `--output, -o` - Output location (default: ./data_delta)
- `--dry-run` - Show migration plan without executing
- `--no-delete` - Keep original Parquet files after migration

**Examples:**
```bash
# Dry run for all datasets
uv run python scripts/migration/migrate_to_delta.py migrate --all --dry-run

# Migrate stocks dataset
uv run python scripts/migration/migrate_to_delta.py migrate --dataset stocks

# Migrate to S3 and keep originals
uv run python scripts/migration/migrate_to_delta.py migrate --all \
    --output s3://ibapi-data/warehouse \
    --no-delete
```

#### `verify`

Verify migrated Delta table matches original Parquet data.

**Arguments:**
- `dataset` - Dataset name (e.g., stocks)
- `table` - Table name (e.g., historical_bars)

**Options:**
- `--delta-path` - Delta Lake data directory (default: ./data_delta)
- `--parquet-path` - Original Parquet directory (default: ./data)

**Examples:**
```bash
# Verify stocks.historical_bars
uv run python scripts/migration/migrate_to_delta.py verify stocks historical_bars

# With custom paths
uv run python scripts/migration/migrate_to_delta.py verify options option_bars \
    --delta-path ./my_delta_data \
    --parquet-path ./data_backup
```

**Verification Checks:**
- ✅ Row count comparison
- ✅ Schema comparison (column names)
- ✅ Exit code 0 on success, 1 on failure

## Backup Script (backup_data.sh)

### Usage

```bash
# Interactive backup to default location
./scripts/migration/backup_data.sh

# Non-interactive with custom location
./scripts/migration/backup_data.sh /path/to/backup
```

### Features

- Uses `rsync` for efficient copying with progress
- Creates timestamped backups (data_backup_YYYYMMDD_HHMMSS)
- Generates manifest file (BACKUP_MANIFEST.txt) with:
  - Backup date and time
  - Source and destination paths
  - File count and size
  - Dataset list
  - Restore instructions

### Backup Manifest Example

```
dlt-ibapi Data Backup Manifest
==============================

Backup Date:    2025-11-14 10:30:00
Source:         ./data
Destination:    ./data_backup_20251114_103000
Source Size:    1.2G
Files Backed up: 1500

Datasets:
  - stocks
  - options
  - option_chains
  - earnings

To restore:
  rm -rf ./data
  cp -r ./data_backup_20251114_103000 ./data

To verify:
  diff -r ./data ./data_backup_20251114_103000
```

## Migration Workflow

### Option 1: In-Place Migration (Recommended)

Migrate existing data while keeping a backup:

```bash
# 1. Backup
./scripts/migration/backup_data.sh

# 2. Dry run
uv run python scripts/migration/migrate_to_delta.py migrate --all --dry-run

# 3. Migrate to new location
uv run python scripts/migration/migrate_to_delta.py migrate --all --output ./data_delta

# 4. Verify
uv run python scripts/migration/migrate_to_delta.py verify stocks historical_bars --delta-path ./data_delta

# 5. Update storage_config.yaml
# Change: base_path: ./data_delta
# Change: use_delta: true

# 6. Test with Delta Lake
uv run dlt-ibapi stats ./data_delta --dataset stocks
```

### Option 2: Side-by-Side Migration

Keep both Parquet and Delta Lake:

```bash
# 1. Migrate to separate directory
uv run python scripts/migration/migrate_to_delta.py migrate --all --output ./data_delta

# 2. Verify
uv run python scripts/migration/migrate_to_delta.py verify stocks historical_bars --delta-path ./data_delta

# 3. Use both:
# - Parquet: uv run dlt-ibapi backfill-equity AAPL
# - Delta Lake: uv run dlt-ibapi backfill-equity AAPL --delta

# Both write to their respective locations
```

### Option 3: Cloud Migration (S3/MinIO)

Migrate to cloud storage:

```bash
# 1. Start MinIO (if using local S3)
docker-compose -f ../delta-lake-storage/templates/docker/docker-compose.yml up -d

# 2. Configure S3 credentials in .dlt/secrets.toml
cat > .dlt/secrets.toml <<EOF
[destination.filesystem.credentials]
aws_access_key_id = "minioadmin"
aws_secret_access_key = "minioadmin"
endpoint_url = "http://localhost:9000"
region_name = "us-east-1"
EOF

# 3. Migrate to S3
uv run python scripts/migration/migrate_to_delta.py migrate --all --output s3://ibapi-data/warehouse

# 4. Verify in MinIO console
open http://localhost:9001

# 5. Update storage_config.yaml
# Change: backend: s3
# Change: bucket_url: s3://ibapi-data/warehouse
# Change: use_delta: true
```

## Rollback

If you need to rollback to Parquet-only:

```bash
# 1. Restore from backup
rm -rf ./data
cp -r ./data_backup_YYYYMMDD_HHMMSS ./data

# 2. Update storage_config.yaml
# Change: backend: filesystem
# Change: base_path: ./data
# Change: use_delta: false

# 3. Verify
uv run dlt-ibapi stats ./data --dataset stocks
```

## Troubleshooting

### Migration fails with "No such file or directory"

**Cause**: Source directory doesn't exist or is empty

**Solution**: Check that `./data` exists and contains datasets:
```bash
ls -la ./data/
```

### Verification fails with "Row count mismatch"

**Cause**: Migration may have been interrupted or data was modified

**Solution**: Re-run migration for that specific dataset:
```bash
uv run python scripts/migration/migrate_to_delta.py migrate --dataset stocks --output ./data_delta
```

### "ImportError: cannot import name 'DeltaTable'"

**Cause**: Delta Lake dependencies not installed

**Solution**: Install dependencies:
```bash
uv sync
```

### MinIO connection failed

**Cause**: MinIO not running or credentials incorrect

**Solution**: Start MinIO and check credentials:
```bash
docker-compose -f ../delta-lake-storage/templates/docker/docker-compose.yml up -d
cat .dlt/secrets.toml
```

## Additional Resources

- **Complete Migration Guide**: [DELTA_LAKE_MIGRATION.md](../../DELTA_LAKE_MIGRATION.md)
- **delta-lake-storage README**: `/Users/mohamedali/trading_project/delta-lake-storage/README.md`
- **Delta Lake Docs**: https://delta.io/
- **DLT Docs**: https://dlthub.com/docs/

## Support

For issues or questions:
1. Check [DELTA_LAKE_MIGRATION.md](../../DELTA_LAKE_MIGRATION.md)
2. Review delta-lake-storage README
3. Check Delta Lake docs: https://delta.io/
