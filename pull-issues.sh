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
# Get all issues as JSON. We use --limit 1000 as a simple way to get "all".
gh issue list --limit 1000 --json number,title,body,state,labels -R $REPO | jq -c '.[]' | while IFS= read -r issue; do

  # --- Parse JSON data ---
  NUMBER=$(echo "$issue" | jq -r .number)
  TITLE=$(echo "$issue" | jq -r .title | sed 's/"/\\"/g') # Escape quotes for YAML
  STATE=$(echo "$issue" | jq -r .state)
  # Get labels as a YAML list (e.g., "- bug\n- enhancement")
  LABELS=$(echo "$issue" | jq -r '.labels | .[] | .name' | sed 's/^/- /')

  # Handle null/empty bodies
  BODY=$(echo $issue | jq -r .body)
  if [ "$BODY" == "null" ]; then
    BODY=""
  fi

  # --- Define File Content ---
  # Using printf is safer for writing multi-line content
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
    # If it was closed before, remove the old file
    rm -f "$CLOSED_DIR/$NUMBER.md"
  else
    FILE_PATH="$CLOSED_DIR/$NUMBER.md"
    # If it was open before, remove the old file
    rm -f "$OPEN_DIR/$NUMBER.md"
  fi

  # --- Write File ---
  printf "%s" "$CONTENT" > $FILE_PATH
  echo "Synced $FILE_PATH"

done

echo "Sync complete."
