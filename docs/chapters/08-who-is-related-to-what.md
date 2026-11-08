# Who is related to what

```{python echo=false output=false}
import glob, os

for f in glob.glob("helpdesk.db*"):
    os.remove(f)
```

A ticket rarely stands alone. María opened two tickets about the same bike,
which came in an order that also had a helmet, and one of the tickets was
escalated to the brand's warranty desk. When she calls, the agent wants the
whole picture: her orders, the tickets on each, and what links them. With
dictionaries, every record keeps lists of ids pointing at the others:

```{python continue}
from beaver import BeaverDB

db = BeaverDB("helpdesk.db")
customers = db.dict("customers")
orders = db.dict("orders")

customers["maria"] = {"orders": ["O-501"]}
orders["O-501"] = {"customer": "maria", "tickets": ["T-1001"]}

# A new ticket about the same order:
order = orders["O-501"]
order["tickets"].append("T-1002")
orders["O-501"] = order

print(orders["O-501"])
```

Each link is written twice, once on each side, and nothing keeps the two
sides in step: one missed update and the customer's page and the order's page
disagree. Asking "which customer is this ticket about?" means scanning every
order for the ticket id.

## A graph

`db.graph(name)` stores directed edges between ids. `link(source, target,
label)` adds one, with optional metadata. Each edge is written once, and can
be read from either end: `children(source)` lists the targets of a node's
edges, and `parents(target)` the sources, both optionally only for one
label.

```{python continue}
g = db.graph("desk")
g.link("maria", "O-501", "ordered")
g.link("O-501", "T-1001", "about")
g.link("O-501", "T-1002", "about")
g.link("T-1002", "T-1001", "duplicate_of")
g.link("T-1001", "warranty:shimano", "escalated", {"case": "SH-7781"})

print(list(g.children("O-501")))
print(list(g.parents("T-1001")))
print(list(g.parents("T-1001", label="about")))
```

## Edges with data

`edges(source)` returns the edges themselves, each an `Edge` with `source`,
`target`, `label` and `metadata`. `get(source, target, label)` reads one,
`linked(...)` says whether it exists, and `unlink(...)` removes it. Linking
the same three again replaces the metadata.

```{python continue}
for e in g.edges("T-1001"):
    print(e.label, "->", e.target, e.metadata)

print(g.linked("T-1002", "T-1001", "duplicate_of"))
g.unlink("T-1002", "T-1001", "duplicate_of")
print(g.linked("T-1002", "T-1001", "duplicate_of"), g.count(), "edges")
```

## Walking further

The graph answers one hop at a time. Longer walks are loops over those hops,
which is usually what a helpdesk page needs: two or three steps from a known
node.

```{python continue}
def tickets_of(customer):
    return [t for order in g.children(customer, label="ordered") for t in g.children(order, label="about")]


def customer_of(ticket):
    for order in g.parents(ticket, label="about"):
        for customer in g.parents(order, label="ordered"):
            return customer


print(tickets_of("maria"), customer_of("T-1002"))
db.close()
```

## The program

The customer view of the desk: every ticket of a customer, through their
orders, with any escalation.

```{python export=examples/customer_view.py}
from beaver import BeaverDB


def record_order(db: BeaverDB, customer: str, order: str) -> None:
    db.graph("desk").link(customer, order, "ordered")


def record_ticket(db: BeaverDB, order: str, ticket: str) -> None:
    db.graph("desk").link(order, ticket, "about")


def escalate(db: BeaverDB, ticket: str, desk: str, case: str) -> None:
    db.graph("desk").link(ticket, desk, "escalated", {"case": case})


def customer_view(db: BeaverDB, customer: str) -> list[str]:
    g = db.graph("desk")
    lines = []
    for order in g.children(customer, label="ordered"):
        for ticket in g.children(order, label="about"):
            escalations = [e for e in g.edges(ticket) if e.label == "escalated"]
            note = "".join(f" (escalated to {e.target}, case {e.metadata['case']})" for e in escalations)
            lines.append(f"{order} / {ticket}{note}")
    return lines


def main():
    with BeaverDB("helpdesk.db") as db:
        db.graph("desk").clear()
        record_order(db, "maria", "O-501")
        record_ticket(db, "O-501", "T-1001")
        record_ticket(db, "O-501", "T-1002")
        escalate(db, "T-1001", "warranty:shimano", "SH-7781")
        for line in customer_view(db, "maria"):
            print(line)


if __name__ == "__main__":
    main()
```
