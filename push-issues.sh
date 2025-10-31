#!/bin/bash
set -e

OPEN_DIR="issues"
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)

echo "Checking for local modifications to sync..."

git status --porcelain "$OPEN_DIR/" | grep '\.md$' | while read -r line; do

  # Get the file path (this works for all statuses, including 'D')
  FILE=$(echo "$line" | awk '{print $NF}')

  echo "---"
  echo "Processing $FILE..."

  # ✅ FIX: Check if the file exists *before* trying to read it
  if [ ! -f "$FILE" ]; then
    # --- FILE IS DELETED ---
    echo "File not found. Assuming deletion."

    # Parse the issue number from the FILENAME (e.g., "issues/123.md")
    NUMBER=$(basename "$FILE" .md)

    # Safety check: If filename isn't a number, skip
    if ! [[ "$NUMBER" =~ ^[0-9]+$ ]]; then
      echo "Skipping deleted file $FILE (could not parse issue number from name)."
      continue
    fi

    # Check if issue is already closed
    CURRENT_STATE=$(gh issue view $NUMBER --json state --repo $REPO -q .state)
    if [ "$CURRENT_STATE" == "open" ]; then
        echo "Closing Issue #$NUMBER on GitHub..."
        gh issue close $NUMBER --repo $REPO
    else
        echo "Issue #$NUMBER is already closed."
    fi

  else
    # --- FILE EXISTS ---

    # --- 1. Parse Local File ---
    NUMBER=$(grep '^number: ' "$FILE" | awk '{print $2}')
    TITLE=$(grep '^title: ' "$FILE" | sed -E 's/^title: "(.*)"$/\1/' | sed -E "s/^title: '(.*)'$/\1/")
    STATE=$(grep '^state: ' "$FILE" | awk '{print $2}')
    if [ -z "$STATE" ]; then
      STATE="open"
    fi
    BODY_FILE=$(mktemp)
    awk 'NR>1 && /^---$/ {f=1; next} f' "$FILE" > $BODY_FILE

    # --- 2. Process Based on NUMBER ---
    if [ -z "$NUMBER" ]; then
      # --- CREATE NEW ISSUE ---
      if [ -z "$TITLE" ]; then
          echo "ERROR: New file $FILE is missing 'title:'. Skipping."
          rm $BODY_FILE
          continue
      fi

      echo "Creating new issue with title: $TITLE"
      NEW_ISSUE_URL=$(gh issue create --title "$TITLE" --body-file $BODY_FILE --repo $REPO)
      NEW_NUMBER=$(echo "$NEW_ISSUE_URL" | awk -F'/' '{print $NF}')
      echo "Created Issue #$NEW_NUMBER. Updating $FILE with new number..."

      sed -i.bak "s/^---$/---\
number: $NEW_NUMBER/" "$FILE" && rm -f "$FILE.bak"

      echo "Successfully updated $FILE. You should 'git add' this change."

    else
      # --- UPDATE EXISTING ISSUE ---
      echo "Updating Issue #$NUMBER..."

      gh issue edit $NUMBER --title "$TITLE" --body-file $BODY_FILE --repo $REPO

      CURRENT_STATE=$(gh issue view $NUMBER --json state --repo $REPO -q .state)

      if [ "$STATE" == "closed" ] && [ "$CURRENT_STATE" == "open" ]; then
        echo "Closing Issue #$NUMBER..."
        gh issue close $NUMBER --repo $REPO
      elif [ "$STATE" == "open" ] && [ "$CURRENT_STATE" == "closed" ]; then
        echo "Reopening Issue #$NUMBER..."
        gh issue reopen $NUMBER --repo $REPO
      fi
    fi

    rm $BODY_FILE
  fi
done

echo "---"
echo "Sync complete."