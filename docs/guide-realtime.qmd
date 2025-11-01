# Real-Time Data

**Chapter Outline:**

* **6.1. Publish/Subscribe (`db.channel`)**
    * High-efficiency, multi-process messaging.
    * Publishing: `channel.publish(payload)`.
    * Subscribing: `with channel.subscribe() as listener: for msg in listener.listen(): ...`
* **6.2. Time-Indexed Logs (`db.log`)**
    * Creating structured, time-series logs: `logs.log(data)`.
    * Querying history: `.range(start_time, end_time)`.
    * **Feature:** Creating a live dashboard with `.live(window, period, aggregator)`.
