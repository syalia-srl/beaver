from beaver import BeaverDB


def claim(db: BeaverDB, agent: str, ticket: str) -> bool:
    """Make `agent` the owner of `ticket` unless someone else already is."""
    owners = db.dict("owners")
    with db.lock(f"claim:{ticket}", timeout=5):
        owner = owners.fetch(ticket)
        if owner not in (None, agent):
            return False
        owners[ticket] = agent
        return True


def main():
    with BeaverDB("helpdesk.db") as db:
        db.dict("owners").clear()
        print("ana claims T-6001:", claim(db, "ana", "T-6001"))
        print("luis claims T-6001:", claim(db, "luis", "T-6001"))
        print("owner:", db.dict("owners")["T-6001"])


if __name__ == "__main__":
    main()
