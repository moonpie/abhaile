#!/bin/bash
# logging.sh - shared logging utilities (common)

# Color codes (use readonly to avoid accidental mutation)
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*" >&2; }
log_ok()   { echo -e "${GREEN}[OK]${NC} $*" >&2; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*" >&2; }
log_error(){ echo -e "${RED}[ERROR]${NC} $*" >&2; }
