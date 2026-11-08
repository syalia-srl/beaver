<div style="text-align: center;">
  <img src="https://github.com/syalia-srl/beaver/blob/main/logo.png?raw=true" width="256px">
</div>

---

<!-- Project badges -->
![PyPI - Version](https://img.shields.io/pypi/v/beaver-db)
![PyPi - Python Version](https://img.shields.io/pypi/pyversions/beaver-db)
![Github - Open Issues](https://img.shields.io/github/issues-raw/syalia-srl/beaver)
![PyPi - Downloads (Monthly)](https://img.shields.io/pypi/dm/beaver-db)
![Github - Commits](https://img.shields.io/github/commit-activity/m/syalia-srl/beaver)

-----

`beaver` is a simple, local, and embedded database designed to manage complex, modern data types without requiring a database server, built on top of SQLite.

## Design Philosophy

`beaver` is built with a minimalistic philosophy for small, local use cases where a full-blown database server would be overkill.

  * **Minimal Dependencies**: The core library depends on `aiosqlite`, `numpy`, `pydantic`, `rich` and `typer`. The HTTP server and encryption are optional extras.
  * **Safe Concurrency**: Thread-safe and multi-process-safe, with inter-process locks stored in the file.
  * **Local-First**: A single, portable SQLite file is the default.
  * **Standard SQLite**: The database file is a standard SQLite file that any SQLite tool can open.
  * **Pythonic API**: Designed to feel like a natural extension of your code, using standard Python data structures and Pydantic models.

## Installation

```bash
pip install beaver-db                 # the core
pip install "beaver-db[full]"         # plus encryption and the HTTP server
```

## Documentation

The guide at [**beaver.syalia.com/docs**](https://beaver.syalia.com/docs/) follows one small project, a bike shop's support desk, from a dictionary of settings to the whole helpdesk on several machines. Every code block in it runs against the package when the site is built. One chapter per need:

  * [Settings that survive a restart](https://beaver.syalia.com/docs/the-shops-settings.html): `BeaverDB` and dictionaries.
  * [Typed records, hashed passwords, encryption and expiring keys](https://beaver.syalia.com/docs/signing-agents-in.html).
  * [Ordered lists](https://beaver.syalia.com/docs/a-tickets-thread.html) and [priority queues shared by workers](https://beaver.syalia.com/docs/the-ticket-queue.html).
  * [Locks across processes](https://beaver.syalia.com/docs/one-agent-per-ticket.html).
  * [Full-text and fuzzy search with filters](https://beaver.syalia.com/docs/finding-a-ticket.html), [vector search](https://beaver.syalia.com/docs/similar-tickets.html) and [graphs](https://beaver.syalia.com/docs/who-is-related-to-what.html).
  * [Blobs, and exporting a collection](https://beaver.syalia.com/docs/attachments.html).
  * [Time-indexed logs](https://beaver.syalia.com/docs/what-happened-and-when.html), [channels and event callbacks](https://beaver.syalia.com/docs/telling-agents-right-away.html), and [probabilistic sketches](https://beaver.syalia.com/docs/the-same-email-twice.html).
  * [The async engine and transactions](https://beaver.syalia.com/docs/a-web-handler.html), [the HTTP server and client](https://beaver.syalia.com/docs/several-machines.html), and [typing your code against the protocols](https://beaver.syalia.com/docs/testing-without-a-database.html).
  * [Migrating a 1.x file](https://beaver.syalia.com/docs/opening-a-1x-file.html), [the whole helpdesk in one program](https://beaver.syalia.com/docs/the-helpdesk-end-to-end.html), and [how beaver is built](https://beaver.syalia.com/docs/inside-beaver.html).

The programs of each chapter are in [`docs/examples/`](docs/examples/).

## Contributing

Contributions are welcome! If you think of something that would make `beaver` more useful for your use case, please open an issue or submit a pull request.

## License

This project is licensed under the MIT License.
