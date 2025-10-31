#!/bin/bash
set -e

OPEN_DIR="issues"
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)

echo "Checking for local modifications to sync..."

# Use 'git status' to find all changed, added, or untracked .md files.
# This is much faster than 'find'.
git status --porcelain "$OPEN_DIR/" | grep '\.md$' | while read -r line; do

  # Get the file path (it's the last field, handles spaces in names)
  FILE=$(echo "$line" | awk '{print $NF}')

  echo "---"
  echo "Processing $FILE..."

  # --- 1. Parse Local File ---

  # Get number (will be blank for new files)
  NUMBER=$(grep '^number: ' "$FILE" | awk '{print $2}')

  # Get title
  TITLE=$(grep '^title: ' "$FILE" | sed -E 's/^title: "(.*)"$/\1/' | sed -E "s/^title: '(.*)'$/\1/")

  # Get state
  STATE=$(grep '^state: ' "$FILE" | awk '{print $2}')
  if [ -z "$STATE" ]; then
    STATE="open"
  fi

  # Get body
  BODY_FILE=$(mktemp)
  awk 'NR>1 && /^---$/ {f=1; next} f' "$FILE" > $BODY_FILE

  # --- 2. Process Based on NUMBER ---

  # The logic is simple. No number? Create. Number? Update.
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

    # Edit the file in place to add the number
    sed -i.bak "s/^---$/---\
number: $NEW_NUMBER/" "$FILE" && rm -f "$FILE.bak"

    echo "Successfully updated $FILE. You should 'git add' this change."

  else
    # --- UPDATE EXISTING ISSUE ---
    # This is a "dumb" push as requested. It doesn't check for remote
    # changes, it just overwrites the remote with your local file's content.
    echo "Updating Issue #$NUMBER..."

    # A) Sync Title and Body
    gh issue edit $NUMBER --title "$TITLE" --body-file $BODY_FILE --repo $REPO

    # B) Sync State (but check first to avoid needless API call)
    CURRENT_STATE=$(gh issue view $NUMBER --json state --repo $REPO -q .state)

    if [ "$STATE" == "closed" ] && [ "$CURRENT_STATE" == "open" ]; then
      echo "Closing Issue #$NUMBER..."
      gh issue close $NUMBER --repo $REPO
    elif [ "$STATE" == "open" ] && [ "$CURRENT_STATE" == "closed" ]; then
      echo "Reopening Issue #$NUMBER..."
      gh issue reopen $NUMBER --repo $REPO
    fi
  fi

  # Clean up temp file
  rm $BODY_FILE
done

echo "---"
echo "Sync complete."