from beaver import BeaverDB

DEFAULTS = {
    "shop": "Spoke & Chain",
    "hours": {"open": 9, "close": 18},
    "greeting": "Thanks for writing to Spoke & Chain!",
}


def ensure_defaults(db: BeaverDB) -> None:
    settings = db.dict("settings")
    for key, value in DEFAULTS.items():
        if key not in settings:
            settings[key] = value


def main():
    with BeaverDB("helpdesk.db") as db:
        ensure_defaults(db)
        settings = db.dict("settings")
        hours = settings["hours"]
        print(f"{settings['shop']} is open {hours['open']}:00 to {hours['close']}:00")


if __name__ == "__main__":
    main()
