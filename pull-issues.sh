#!/bin/bash
set -e

# --- Configuration ---
OPEN_DIR="issues"
CLOSED_DIR="issues/closed"
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)

echo "Syncing all issues from $REPO..."

# --- Setup ---
mkdir -p $OPEN_DIR
mkdir -p $CLOSED_DIR

# --- Fetch Issues ---
# This is the original, simple loop. No tsv, no nul.
gh issue list --limit 1000 --json number,title,body,state,labels -R $REPO | \
  jq -c '.[]' | while IFS= read -r issue; do

  # --- Parse JSON data ---
  NUMBER=$(echo "$issue" | jq -r .number)
  TITLE=$(echo "$issue" | jq -r .title | sed 's/"/\\"/g') # Escape quotes for YAML
  STATE=$(echo "$issue" | jq -r .state)
  LABELS=$(echo "$issue" | jq -r '.labels | .[] | .name' | sed 's/^/- /')

  # Get the body. jq -r un-escapes it.
  BODY=$(echo "$issue" | jq -r .body)

  if [ "$BODY" == "null" ]; then
    BODY=""
  fi

  # --- Define File Content ---
  CONTENT="---
number: $NUMBER
title: \"$TITLE\"
state: $STATE
labels:
$LABELS
---
$BODY
"

  # --- File & Directory Logic ---
  if [ "$STATE" == "OPEN" ]; then
    FILE_PATH="$OPEN_DIR/$NUMBER.md"
    rm -f "$CLOSED_DIR/$NUMBER.md"
  else
    FILE_PATH="$CLOSED_DIR/$NUMBER.md"
    rm -f "$OPEN_DIR/$NUMBER.md"
  fi

  # --- Write File ---
  printf "%s" "$CONTENT" > $FILE_PATH
  echo "Wrote $FILE_PATH"

done

echo "Sync complete."