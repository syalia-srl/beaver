import sqlite3
import sys


def inspect(path: str) -> list[str]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        lines = [f"{path}: schema version {version}"]
        names = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name LIKE '__beaver%' ORDER BY name"
        ).fetchall()
        for (name,) in names:
            rows = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            if rows:
                lines.append(f"  {name:<32} {rows} rows")
        return lines
    finally:
        conn.close()


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        from beaver import BeaverDB

        path = "inspect-demo.db"
        with BeaverDB(path) as db:
            db.dict("settings")["shop"] = "Spoke & Chain"
    print("\n".join(inspect(path)))


if __name__ == "__main__":
    main()
