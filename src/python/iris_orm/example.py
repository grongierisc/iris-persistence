"""
iris_orm usage example
======================

This file demonstrates how to define IRIS persistent classes, perform
CRUD operations, and use the query API.

Prerequisites
-------------
- A running IRIS instance with the ``iris`` Python package available.
- The following IRIS classes must exist (or adapt the classnames below):

    Class Demo.Person Extends %Persistent
    {
        Property Name As %String;
        Property Age  As %Integer;
        Property DOB  As %Date;
    }

    Class Demo.Post Extends %Persistent
    {
        Property Title   As %String;
        Property Body    As %String(MAXLEN=32768);
        Property Author  As %String;
        Property Created As %TimeStamp;
        Property Views   As %Integer;
    }

Running
-------
Inside an IRIS Python shell or embedded Python context::

    python example.py
"""
from iris_orm import IRISModel


# ---------------------------------------------------------------------------
# 1. Model definitions
#    Just set _iris_classname — the metaclass does the rest.
# ---------------------------------------------------------------------------

class Person(IRISModel):
    _iris_classname = "Demo.Person"
    # IRISMeta auto-injects: Name (str), Age (int), DOB (datetime.date)


class Post(IRISModel):
    _iris_classname = "Demo.Post"
    # IRISMeta auto-injects: Title, Body, Author (str), Created (datetime), Views (int)


# ---------------------------------------------------------------------------
# 2. Create & save
# ---------------------------------------------------------------------------

def create_examples() -> None:
    alice = Person.create(Name="Alice", Age=30)
    alice.save()
    print(f"Saved Alice with pk={alice.pk}")

    bob = Person.create(Name="Bob", Age=25)
    bob.save()
    print(f"Saved Bob   with pk={bob.pk}")

    post = Post.create(
        Title="Hello IRIS ORM",
        Body="This post was created from Python.",
        Author="Alice",
        Views=0,
    )
    post.save()
    print(f"Saved Post  with pk={post.pk}")


# ---------------------------------------------------------------------------
# 3. Open by ID
# ---------------------------------------------------------------------------

def open_by_id(person_id: str) -> None:
    person = Person.get(person_id)
    if person is None:
        print(f"Person {person_id!r} not found")
        return
    print(f"Opened: Name={person.Name!r}  Age={person.Age}")


# ---------------------------------------------------------------------------
# 4. Update a property
# ---------------------------------------------------------------------------

def birthday(person_id: str) -> None:
    person = Person.get(person_id)
    if person is None:
        return
    person.Age = (person.Age or 0) + 1
    person.save()
    print(f"Happy birthday {person.Name}! Now {person.Age}.")


# ---------------------------------------------------------------------------
# 5. Query — all(), filter(), count(), first()
# ---------------------------------------------------------------------------

def query_examples() -> None:
    # All persons
    print("All persons:")
    for p in Person.objects.all():
        print(f"  [{p.pk}] {p.Name}, age {p.Age}")

    # Filter
    print("Posts by Alice:")
    for post in Post.objects.filter(Author="Alice"):
        print(f"  [{post.pk}] {post.Title!r}  views={post.Views}")

    # Count
    total = Person.objects.count()
    print(f"Total persons: {total}")

    # First
    first_post = Post.objects.first()
    if first_post:
        print(f"First post: {first_post.Title!r}")


# ---------------------------------------------------------------------------
# 6. Delete
# ---------------------------------------------------------------------------

def delete_example(person_id: str) -> None:
    person = Person.get(person_id)
    if person is None:
        print("Not found, nothing to delete.")
        return
    name = person.Name
    person.delete()
    print(f"Deleted {name!r} (pk={person_id}). pk after delete: {person.pk}")


# ---------------------------------------------------------------------------
# 7. Stub generation (offline, no IRIS needed for the CLI itself)
# ---------------------------------------------------------------------------

def show_stub_command() -> None:
    print(
        "\nTo generate .pyi stubs for IDE auto-complete, run:\n"
        "  python -m iris_orm.stubs Demo.Person ./src/python/\n"
        "  python -m iris_orm.stubs Demo.Post   ./src/python/\n"
        "This writes Demo/Person.pyi and Demo/Post.pyi.\n"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    create_examples()
    query_examples()
    show_stub_command()
