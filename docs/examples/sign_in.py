import secrets

from pydantic import BaseModel

from beaver import BeaverDB, Secret

SESSION_SECONDS = 8 * 3600


class Agent(BaseModel):
    name: str
    role: str
    password: Secret


def add_agent(db: BeaverDB, login: str, name: str, role: str, password: str):
    db.dict("accounts", model=Agent)[login] = Agent(
        name=name, role=role, password=Secret(password)
    )


def sign_in(db: BeaverDB, login: str, password: str) -> str | None:
    agent = db.dict("accounts", model=Agent).fetch(login)
    if agent is None or agent.password != password:
        return None
    token = secrets.token_hex(16)
    db.dict("sessions").set(token, login, ttl_seconds=SESSION_SECONDS)
    return token


def who(db: BeaverDB, token: str) -> str | None:
    return db.dict("sessions").fetch(token)


def main():
    with BeaverDB("helpdesk.db") as db:
        add_agent(db, "luis", "Luis", "agent", "battery-staple")
        print("wrong password:", sign_in(db, "luis", "guess"))
        token = sign_in(db, "luis", "battery-staple")
        print("signed in as:", who(db, token))


if __name__ == "__main__":
    main()
