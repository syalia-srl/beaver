Beaver is an embedded database for Python that keeps every kind of data an
application needs in one SQLite file: key-value dictionaries, lists, priority
queues, searchable documents, vectors, graphs, files, time-ordered logs, locks,
live channels and probabilistic sets. It needs Python 3.12 or later.

```bash
pip install beaver-db                 # the core
pip install "beaver-db[security]"     # encrypted dictionaries and hashed secrets
pip install "beaver-db[remote]"       # the HTTP server and its client
pip install "beaver-db[full]"         # all of the above
```

The file stays a standard SQLite database: you can open it with `sqlite3` at
any time, copy it, back it up, and ship it with your program. There is no
server to run until you want one.

This guide follows one small project: the support desk of a bike shop,
Spoke & Chain. Customers write in, agents answer, and the desk slowly grows the
pieces every helpdesk grows. Each chapter starts with a job the desk needs
done, tries it first with plain Python or with what the earlier chapters
taught, shows where that breaks, and then fixes it with one or two pieces of
beaver. Later chapters reuse the data of the earlier ones, and chapter 17 puts
everything together.

**Keeping state**

1. **The shop's settings.** Values that survive a restart, with `BeaverDB` and
   `db.dict()`.
2. **Signing agents in.** Typed records, hashed passwords and sessions that
   expire, with `model=`, `Secret` and `ttl_seconds`.
3. **A ticket's thread.** Ordered messages, with `db.list()`.

**Working together**

4. **The ticket queue.** Urgent tickets first, shared by several workers, with
   `db.queue()`.
5. **One agent per ticket.** Claiming work safely across processes, with
   `db.lock()`.

**Finding things**

6. **Finding a ticket.** Full-text and fuzzy search with filters, with
   `db.docs()` and `q`.
7. **Similar tickets.** Nearest neighbours over embeddings, with
   `db.vectors()`.
8. **Who is related to what.** Customers, orders and tickets as a graph, with
   `db.graph()`.
9. **Attachments.** Photos and invoices, with `db.blob()`.

**Watching**

10. **What happened and when.** An audit trail you can query by time, with
    `db.log()`.
11. **Telling agents right away.** Live notifications, with `db.channel()` and
    `db.events()`.
12. **The same email twice.** Remembering millions of message ids in a few
    megabytes, with `db.sketch()`.

**Growing up**

13. **A web handler.** The async engine, transactions and the cache, with
    `AsyncBeaverDB`.
14. **Several machines.** The HTTP server and its client, with `beaver serve`
    and `BeaverClient`.
15. **Testing without a database.** Writing code against the `IBeaver*`
    protocols.
16. **Opening a 1.x file.** Migrating an old database, with
    `beaver.migrate`.
17. **The helpdesk, end to end.** All of the above in one program, with
    nothing new.
18. **Inside beaver.** How the pieces are built, for contributors.

Every Python block in this guide ran against the real package when the page
was built, and the output under it is what it printed. Each chapter ends with
a program in `docs/examples/` that you can run as it is.
