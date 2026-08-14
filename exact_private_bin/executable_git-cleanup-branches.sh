#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# git-cleanup-branches.sh
# Identifies and removes stalled/orphaned remote branches.
#
# Usage:
#   ./scripts/git-cleanup-branches.sh [--delete] [--stale-days N] [remote]
#
# Defaults:
#   remote      : origin
#   stale-days  : 30
#   mode        : dry-run (pass --delete to actually remove branches)
# =============================================================================

REMOTE=""
DRY_RUN=1
DELETE_MERGED=0
DELETE_STALE=0
STALE_DAYS=30
MAIN_BRANCH="main"

# Parse arguments
while [ $# -gt 0 ]; do
    case "$1" in
        --delete)
            DELETE_MERGED=1
            DELETE_STALE=1
            DRY_RUN=0
            shift
            ;;
        --delete-merged)
            DELETE_MERGED=1
            DRY_RUN=0
            shift
            ;;
        --delete-stale)
            DELETE_STALE=1
            DRY_RUN=0
            shift
            ;;
        --stale-days)
            STALE_DAYS="${2:-30}"
            shift 2
            ;;
        --stale-days=*)
            STALE_DAYS="${1#*=}"
            shift
            ;;
        --help|-h)
            cat << 'EOF'
Usage: git-cleanup-branches.sh [options] [remote]

Options:
  --delete              Delete merged AND stale branches (default: dry-run)
  --delete-merged       Delete only merged branches
  --delete-stale        Delete only stale branches
  --stale-days N        Consider branches stale after N days (default: 30)
  --help, -h            Show this help message

Arguments:
  remote                Remote name (default: origin)

Examples:
  ./scripts/git-cleanup-branches.sh                    # Dry run, show all categories
  ./scripts/git-cleanup-branches.sh --delete           # Delete merged + stale
  ./scripts/git-cleanup-branches.sh --delete-merged    # Delete only merged
  ./scripts/git-cleanup-branches.sh --delete-stale --stale-days 14
EOF
            exit 0
            ;;
        --*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            REMOTE="$1"
            shift
            ;;
    esac
done

REMOTE="${REMOTE:-origin}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

git_date_to_unix() {
    git log -1 --format='%ct' "$1" 2>/dev/null || echo 0
}

days_since() {
    local unix_ts="$1"
    local now
    now=$(date +%s)
    echo $(( (now - unix_ts) / 86400 ))
}

format_date() {
    git log -1 --format='%ai' "$1" 2>/dev/null | cut -d' ' -f1
}

branch_age_info() {
    local branch="$1"
    local unix_ts
    unix_ts=$(git_date_to_unix "$branch")
    local days
    days=$(days_since "$unix_ts")
    local date_str
    date_str=$(format_date "$branch")
    printf "%s (%s days old, last: %s)" "$branch" "$days" "$date_str"
}

is_protected() {
    local branch="$1"
    local short_name="${branch#$REMOTE/}"
    case "$short_name" in
        main|master|develop|release/*|HEAD)
            return 0
            ;;
    esac
    return 1
}

# ---------------------------------------------------------------------------
# Fetch latest remote state
# ---------------------------------------------------------------------------

echo -e "${BOLD}Fetching remote branches from $REMOTE...${NC}"
git fetch --prune "$REMOTE" 2>/dev/null || true
echo ""

# ---------------------------------------------------------------------------
# Categorize branches
# ---------------------------------------------------------------------------

MERGED_BRANCHES=()
STALE_BRANCHES=()
WORKTREE_BRANCHES=()
OTHER_BRANCHES=()

while IFS= read -r branch; do
    [ -z "$branch" ] && continue
    [ "$branch" = "$REMOTE" ] && continue
    short_name="${branch#$REMOTE/}"

    if is_protected "$branch"; then
        continue
    fi

    # Check if merged into main
    if git branch -r --merged "$REMOTE/$MAIN_BRANCH" --format='%(refname:short)' | grep -qx "$branch"; then
        MERGED_BRANCHES+=("$branch")
        continue
    fi

    # Check age
    unix_ts=$(git_date_to_unix "$branch")
    days=$(days_since "$unix_ts")

    # Check if worktree branch
    if [[ "$short_name" =~ ^worktree- ]]; then
        WORKTREE_BRANCHES+=("$branch")
        if [ "$days" -ge "$STALE_DAYS" ]; then
            STALE_BRANCHES+=("$branch")
        fi
        continue
    fi

    # Regular stale check
    if [ "$days" -ge "$STALE_DAYS" ]; then
        STALE_BRANCHES+=("$branch")
        continue
    fi

    OTHER_BRANCHES+=("$branch")
done < <(git branch -r --format='%(refname:short)' | grep "^$REMOTE/")

# ---------------------------------------------------------------------------
# Display Results
# ---------------------------------------------------------------------------

echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}  Remote Branch Cleanup Report${NC}"
echo -e "${BOLD}============================================${NC}"
echo -e "Remote:     ${CYAN}$REMOTE${NC}"
echo -e "Main branch:${CYAN} $MAIN_BRANCH${NC}"
echo -e "Stale after:${CYAN} $STALE_DAYS days${NC}"
if [ "$DRY_RUN" -eq 1 ]; then
    echo -e "Mode:       ${YELLOW}DRY-RUN${NC} (pass --delete to remove)"
else
    echo -e "Mode:       ${RED}DELETE${NC}"
fi
echo ""

# 1. Merged branches (safest to delete)
if [ ${#MERGED_BRANCHES[@]} -gt 0 ]; then
    echo -e "${GREEN}✓ MERGED into $MAIN_BRANCH (${#MERGED_BRANCHES[@]}) — safest to delete${NC}"
    for b in "${MERGED_BRANCHES[@]}"; do
        echo "    $(branch_age_info "$b")"
    done
    echo ""
fi

# 2. Stale branches
if [ ${#STALE_BRANCHES[@]} -gt 0 ]; then
    echo -e "${YELLOW}⚠ STALE (≥$STALE_DAYS days old) (${#STALE_BRANCHES[@]})${NC}"
    for b in "${STALE_BRANCHES[@]}"; do
        echo "    $(branch_age_info "$b")"
    done
    echo ""
fi

# 3. Worktree branches
if [ ${#WORKTREE_BRANCHES[@]} -gt 0 ]; then
    echo -e "${CYAN}⚡ WORKTREE branches (${#WORKTREE_BRANCHES[@]}) — auto-generated by orchestrator${NC}"
    for b in "${WORKTREE_BRANCHES[@]}"; do
        echo "    $(branch_age_info "$b")"
    done
    echo ""
fi

# 4. Other active branches
if [ ${#OTHER_BRANCHES[@]} -gt 0 ]; then
    echo -e "${BLUE}○ ACTIVE branches (<$STALE_DAYS days old) (${#OTHER_BRANCHES[@]})${NC}"
    for b in "${OTHER_BRANCHES[@]}"; do
        echo "    $(branch_age_info "$b")"
    done
    echo ""
fi

# Summary stats
total=$(( ${#MERGED_BRANCHES[@]} + ${#STALE_BRANCHES[@]} + ${#OTHER_BRANCHES[@]} ))
echo -e "${BOLD}Total remote branches analyzed: $total${NC}"
echo ""

# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------

if [ "$DRY_RUN" -eq 1 ]; then
    echo -e "${YELLOW}Dry run complete. No branches were deleted.${NC}"
    echo ""
    if [ ${#MERGED_BRANCHES[@]} -gt 0 ]; then
        echo -e "Delete merged branches:    ${BOLD}./scripts/git-cleanup-branches.sh --delete-merged${NC}"
    fi
    if [ ${#STALE_BRANCHES[@]} -gt 0 ]; then
        echo -e "Delete stale branches:     ${BOLD}./scripts/git-cleanup-branches.sh --delete-stale --stale-days $STALE_DAYS${NC}"
    fi
    if [ ${#MERGED_BRANCHES[@]} -gt 0 ] && [ ${#STALE_BRANCHES[@]} -gt 0 ]; then
        echo -e "Delete both:               ${BOLD}./scripts/git-cleanup-branches.sh --delete --stale-days $STALE_DAYS${NC}"
    fi
    exit 0
fi

# DELETE mode
echo -e "${RED}${BOLD}Proceeding with deletion...${NC}"
echo ""

delete_branch() {
    local branch="$1"
    local short_name="${branch#$REMOTE/}"
    echo -n "  Deleting $short_name ... "
    if git push "$REMOTE" --delete "$short_name" 2>/dev/null; then
        echo -e "${GREEN}done${NC}"
    else
        echo -e "${RED}failed${NC}"
    fi
}

# Delete merged branches
if [ "$DELETE_MERGED" -eq 1 ] && [ ${#MERGED_BRANCHES[@]} -gt 0 ]; then
    echo -e "${BOLD}Deleting MERGED branches:${NC}"
    for b in "${MERGED_BRANCHES[@]}"; do
        delete_branch "$b"
    done
    echo ""
fi

# Delete stale branches
if [ "$DELETE_STALE" -eq 1 ] && [ ${#STALE_BRANCHES[@]} -gt 0 ]; then
    echo -e "${BOLD}Deleting STALE branches:${NC}"
    for b in "${STALE_BRANCHES[@]}"; do
        delete_branch "$b"
    done
    echo ""
fi

echo -e "${GREEN}${BOLD}Cleanup complete.${NC}"
