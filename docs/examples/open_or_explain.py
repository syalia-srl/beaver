import sys

from beaver import BeaverDB, BeaverIncompatibleSchemaError, BeaverLegacySchemaError
from beaver.migrate import plan_migration


def open_desk(path: str) -> BeaverDB | None:
    try:
        return BeaverDB(path)
    except BeaverLegacySchemaError:
        report = plan_migration(path)
        rows = sum(report.dicts.values()) + sum(report.lists.values())
        print(f"{path} is a beaver {report.legacy_version} file with {rows} rows.")
        print(f"Run: beaver migrate {path} --output {path}.2x")
    except BeaverIncompatibleSchemaError as e:
        print(f"{path} was written by a newer beaver: {e}")
    return None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "helpdesk.db"
    db = open_desk(path)
    if db is not None:
        with db:
            print(f"{path} is ready, {len(db.dict('settings'))} settings")


if __name__ == "__main__":
    main()
