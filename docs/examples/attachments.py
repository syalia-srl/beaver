from beaver import BeaverDB

MAX_BYTES = 10 * 1024 * 1024


def attach(db: BeaverDB, ticket: str, name: str, data: bytes, kind: str) -> str:
    if len(data) > MAX_BYTES:
        raise ValueError(f"{name} is larger than {MAX_BYTES} bytes")
    key = f"{ticket}/{name}"
    db.blob("attachments").put(key, data, {"type": kind, "size": len(data)})
    return key


def attachments_of(db: BeaverDB, ticket: str) -> list[tuple[str, int]]:
    blobs = db.blob("attachments")
    return [
        (key.split("/", 1)[1], blobs.fetch(key).metadata["size"])
        for key in blobs.keys()
        if key.startswith(f"{ticket}/")
    ]


def main():
    with BeaverDB("helpdesk.db") as db:
        db.blob("attachments").clear()
        attach(db, "T-1001", "brake.jpg", b"\xff\xd8 photo", "image/jpeg")
        attach(db, "T-1001", "invoice.pdf", b"%PDF-1.7 invoice", "application/pdf")
        attach(db, "T-1002", "chain.jpg", b"\xff\xd8 photo", "image/jpeg")
        for name, size in attachments_of(db, "T-1001"):
            print(f"{name}: {size} bytes")


if __name__ == "__main__":
    main()
