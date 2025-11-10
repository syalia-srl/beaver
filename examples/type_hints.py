# examples/typed_model.py
from beaver import BeaverDB, Model


# By inheriting from beaver.Model, this class automatically gets
# the serialization methods needed by the database.
class Person(Model):
    name: str
    age: int


def typed_model_demo():
    """Demonstrates using the built-in Model base class for type safety."""
    print("--- Running Typed Model Demo ---")
    db = BeaverDB("typed_model_demo.db")

    # The `model=Person` argument now works seamlessly with our Person class.
    people = db.queue("people", model=Person)

    # Storing an instance of the Person class
    people.put(Person(name="Alice", age=30), priority=2)

    # Retrieving the object
    retrieved_person = people.get()
    assert retrieved_person is not None
    print(f"Retrieved: {retrieved_person.data}")

    # The retrieved object is a proper instance of the Person class
    assert isinstance(retrieved_person.data, Person)
    assert retrieved_person.data.name == "Alice"

    db.close()
    print("\n--- Demo Finished Successfully ---")


if __name__ == "__main__":
    typed_model_demo()
