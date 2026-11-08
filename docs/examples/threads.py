from pydantic import BaseModel

from beaver import BeaverDB


class Message(BaseModel):
    author: str
    text: str
    internal: bool = False


def thread(db: BeaverDB, ticket: str):
    return db.list(f"thread:{ticket}", model=Message)


def public_view(db: BeaverDB, ticket: str) -> list[Message]:
    return [m for m in thread(db, ticket) if not m.internal]


def main():
    with BeaverDB("helpdesk.db") as db:
        t = thread(db, "T-1002")
        t.clear()
        t.push(Message(author="customer", text="The chain skips in 7th gear."))
        t.push(Message(author="luis", text="Check cable tension.", internal=True))
        t.push(Message(author="ana", text="Bring it in, we'll adjust it for free."))
        for m in public_view(db, "T-1002"):
            print(f"{m.author}: {m.text}")


if __name__ == "__main__":
    main()
