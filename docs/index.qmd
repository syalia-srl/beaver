# Introduction

Welcome to BeaverDB!

If you've ever found yourself building a Python application that needs to save some data, but setting up a full-blown database server felt like massive overkill, you're in the right place. BeaverDB is designed to be the "Swiss Army knife" for embedded Python data.  It's built for those exact "just right" scenarios: more powerful than a simple pickle file, but far less complex than a networked server like PostgreSQL or MySQL.

## What is BeaverDB?

At its heart, BeaverDB is a multi-modal database in a single SQLite file.

It's a Python library that lets you manage modern, complex data types without ever leaving the comfort of a local file. The name itself tells the story:

**B.E.A.V.E.R.** stands for **B**ackend for
mbedded, **A**ll-in-one **V**ector, **E**ntity, and **R**elationship storage.

This means that inside that one `.db` file, you can seamlessly store and query:

- Key-Value Pairs (like a dictionary for your app's configuration)
- Lists (like a persistent to-do list)
- Vector Embeddings (for AI and semantic search)
- Documents & Text (for full-text search)
- Graph Relationships (to connect your data together)
- ...and much more.

All this power comes from building on top of the world's most deployed database engine: SQLite.

## The BeaverDB Philosophy

BeaverDB is built on a few core principles. Understanding these will help you know when and why to choose it for your project.

**Robust, Safe, and Durable**

Your data should be safe, period. BeaverDB is built to be resilient. Thanks to SQLite's atomic transactions and Write-Ahead Logging (WAL) mode, your database is crash-safe. If your program crashes mid-operation, your data is never lost or corrupted; the database simply rolls back the incomplete transaction.

Furthermore, it's designed for concurrency. It's both thread-safe (different threads can share one BeaverDB object) and process-safe (multiple, independent Python scripts can read from and write to the same database file at the same time). For tasks that require true coordination, it even provides a simple, built-in distributed lock.

**Performant by Default**

BeaverDB is fast. It's not just "fast for a small database"--it's genuinely fast for the vast majority of medium-sized projects. Because it's an embedded library, there is zero network latency for any query.

Let's be clear: if you're building the next X (formerly Twitter) and need to handle millions of documents and thousands of queries per second, you'll need a distributed, networked database. But for almost everything else? BeaverDB is more than fast enough. If your project is in the thousand to tens-of-thousands of documents range, you'll find it's incredibly responsive.

**Local-First & Embedded**

The default, primary way to use BeaverDB is as a single file right next to your code. This means your entire database—users, vectors, chat logs, and all—is contained in one portable file (e.g., my_app.db). You can copy it, email it, or back it up. This "local-first" approach is what makes it so fast and simple to deploy.

**Minimal & Optional Dependencies**

The core BeaverDB library has zero external dependencies. You can get started with key-value stores, lists, and queues right away.

Want to add vector search? Great! Install the [vector] extra, and BeaverDB will activate its faiss integration. Need a web server? Install the [server] extra, and it unlocks a fastapi-based REST API. This "pay-as-you-go" approach keeps your project lightweight.

**Pythonic API**

BeaverDB is designed to feel like you're just using standard Python data structures. You shouldn't have to write complex SQL queries just to save a Python dict or list. The goal is to make the database feel like a natural extension of your code.

**Standard SQLite Compatibility**

This is the "no-magic" rule. The my_app.db file that BeaverDB creates is a 100% standard, valid SQLite file. You can open it with any database tool (like DB Browser for SQLite) and see your data in regular tables. This ensures your data is never locked into a proprietary format.

**Synchronous Core with Async Potential**

The core library is synchronous, which makes it simple and robust for multi-threaded applications. However, BeaverDB is fully aware of the modern asyncio world. For every data structure, you can call .as_async() to get a fully awaitable version that runs its blocking operations in a background thread, keeping your asyncio event loop from getting blocked.

## Ideal Use Cases

BeaverDB shines in scenarios where simplicity, robustness, and local performance are more important than massive, web-scale concurrency.

- **Local AI & RAG:** Perfect for building Retrieval-Augmented Generation (RAG) applications that run on your local machine. You can store your vector embeddings and their corresponding text right next to each other.

- **Desktop Utilities & CLI Tools:** The ideal companion for a custom tool that needs to remember user preferences, manage a history, or cache results.

- **Chatbots:** A persistent list is a perfect, simple way to store a chatbot's conversation history for a user.

- **Rapid Prototyping:** Get your idea up and running in minutes. Start with a local .db file, and if your project grows, you can deploy it as a REST API without changing your application logic.

## How This Guide is Structured

We've designed this documentation to get you the information you need, whether you're building your first script or contributing to the core.

This guide is split into two main parts:

- **Part 1: The User Guide**

    This is your starting point. After the Quickstart, this is where you'll find an in-depth guide that walks you through how to use every single feature of BeaverDB. We'll explore each "modality" one by one with practical examples.

- **Part 2: The Developer Guide**

    This part is for power users and contributors. We'll go under the hood to look at the why behind the design. This is where we do deep dives into the core architecture, the concurrency model (threading and locking), and the internals of how features like vector search are implemented.
