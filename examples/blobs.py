from beaver import BeaverDB


def blob_store_demo():
    """Demonstrates the basic functionality of the blob store."""
    print("--- Running Blob Store Demo ---")
    db = BeaverDB("demo.db")

    # 1. Get a handle to a named blob store
    attachments = db.blobs("email_attachments")

    # 2. Create some sample binary data
    file_content = "This is the content of a virtual text file."
    file_bytes = file_content.encode("utf-8")
    file_key = "emails/user123/attachment_01.txt"

    # 3. Store the blob with some metadata
    print(f"Storing blob with key: '{file_key}'")
    attachments.put(
        key=file_key,
        data=file_bytes,
        metadata={"mimetype": "text/plain", "sender": "alice@example.com"},
    )

    # 4. Check for the blob's existence
    if file_key in attachments:
        print(f"Verified that key '{file_key}' exists in the store.")

    # 5. Retrieve the blob
    blob = attachments.get(file_key)
    if blob:
        print("\n--- Retrieved Blob ---")
        print(f"  Key: {blob.key}")
        print(f"  Metadata: {blob.metadata}")
        print(f"  Data (decoded): '{blob.data.decode('utf-8')}'")
        assert blob.data == file_bytes

    # 6. Delete the blob
    print("\nDeleting blob...")
    attachments.delete(file_key)

    # 7. Verify deletion
    if file_key not in attachments:
        print(f"Verified that key '{file_key}' has been deleted.")

    db.close()
    print("\n--- Demo Finished Successfully ---")


if __name__ == "__main__":
    blob_store_demo()
