import asyncio

from beaver import AsyncBeaverDB, TransactionTimeoutError


async def claim_and_reply(db: AsyncBeaverDB, ticket: str, agent: str, text: str) -> str:
    try:
        async with db.lock(f"claim:{ticket}", timeout=1):
            owner = await db.dict("owners").fetch(ticket)
            if owner not in (None, agent):
                return f"{ticket} belongs to {owner}"
            async with db.transaction(timeout=2):
                await db.dict("owners").set(ticket, agent)
                await db.list(f"thread:{ticket}").push({"author": agent, "text": text})
                await db.log("audit").log(
                    {"ticket": ticket, "agent": agent, "action": "reply"}
                )
    except (TimeoutError, TransactionTimeoutError):
        return f"{ticket} is busy, try again"
    return f"{agent} replied on {ticket}"


async def main():
    async with AsyncBeaverDB("helpdesk.db") as db:
        await db.dict("owners").clear()
        results = await asyncio.gather(
            claim_and_reply(db, "T-1601", "ana", "On it."),
            claim_and_reply(db, "T-1601", "luis", "Me too."),
        )
        print("\n".join(results))


if __name__ == "__main__":
    asyncio.run(main())
