from beaver import BeaverDB, Document, WalkDirection


def graph_demo():
    """Demonstrates the graph traversal capabilities of a collection."""
    print("--- Running Graph Traversal Demo ---")

    db = BeaverDB("graph_demo.db")
    net = db.collection("social_network")

    # 1. Create Documents to act as nodes in our social network graph
    print("Creating user profiles (nodes)...")
    alice = Document(id="alice", name="Alice", interests=["AI", "Databases"])
    bob = Document(id="bob", name="Bob", interests=["Python", "AI"])
    charlie = Document(id="charlie", name="Charlie", interests=["Databases"])
    diana = Document(id="diana", name="Diana", interests=["AI"])

    net.index(alice)
    net.index(bob)
    net.index(charlie)
    net.index(diana)

    # 2. Create Edges to represent relationships
    print("Creating relationships (edges)...")
    net.connect(alice, bob, label="FOLLOWS")
    net.connect(alice, charlie, label="FOLLOWS")
    net.connect(bob, diana, label="FOLLOWS")
    net.connect(charlie, bob, label="FOLLOWS")

    # Add a different type of relationship
    net.connect(alice, bob, label="COLLABORATES_WITH")

    # --- 3. Using the `neighbors` Method (Single Hop) ---
    print("\n--- Testing `neighbors` (1-hop) ---")

    # Find everyone Alice follows
    following = net.neighbors(alice, label="FOLLOWS")
    print(f"Alice follows: {[p.id for p in following]}")

    # Find who Alice collaborates with
    collaborators = net.neighbors(alice, label="COLLABORATES_WITH")
    print(f"Alice collaborates with: {[p.id for p in collaborators]}")

    # --- 4. Using the `walk` Method (Multi-Hop Traversal) ---
    print("\n--- Testing `walk` (multi-hop) ---")

    # Find the "friends of friends" for Alice, up to 2 steps away
    # This will find Bob, Charlie (depth 1) and then Diana (depth 2, via Bob)
    foaf = net.walk(
        source=alice,
        labels=["FOLLOWS"],
        depth=2,
        direction=WalkDirection.OUTGOING,
    )
    print(f"Alice's extended network (friends of friends): {[p.id for p in foaf]}")

    # Find who follows Bob (incoming walk)
    # This should find Alice and Charlie
    followers = net.walk(
        source=bob,
        labels=["FOLLOWS"],
        depth=1,
        direction=WalkDirection.INCOMING,
    )
    print(f"Bob is followed by: {[p.id for p in followers]}")

    db.close()
    print("\n--- Demo Finished ---")


if __name__ == "__main__":
    graph_demo()
