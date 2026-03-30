"""
iris_orm example — demonstrates existing-class binding and declared models side-by-side.

This file is for illustration only; it will not run without a live IRIS connection.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Existing-class binding
# ---------------------------------------------------------------------------
# The metaclass will query %Dictionary.PropertyDefinition at class definition
# time and inject typed descriptors automatically.

# from iris_orm import IRISModel
#
# class User(IRISModel):
#     _iris_classname = "Demo.User"
#
# # Descriptors are injected: User.Name, User.Email, User.Age, etc.
# # (whatever properties IRIS reports for Demo.User)
#
# user = User.get("1")
# print(user.Name)
#
# new_user = User.create(Name="Alice", Email="alice@example.com")
# new_user.save()
# print(new_user.pk)
#
# for u in User.objects.filter(Name="Alice"):
#     print(u.pk, u.Name)

# ---------------------------------------------------------------------------
# Declared model
# ---------------------------------------------------------------------------
# Typed annotations + field()/relationship() metadata drive everything.
# generate_cls() can emit ObjectScript source; compile_to_iris() can compile it.

from iris_orm import IRISModel, field, relationship
from iris_orm import schema
from iris_orm import stubs


class Author(IRISModel):
    _iris_classname = "Demo.Author"

    Name: str = field(required=True, maxlen=200, description="Full name of the author")
    Email: str = field(maxlen=255, description="Contact email")
    Bio: str = field(description="Short biography")


class Post(IRISModel):
    _iris_classname = "Demo.Post"

    Title: str = field(required=True, maxlen=500, description="Post title")
    Body: str = field(description="Post body text")

    author = relationship(
        "Demo.Author",
        inverse="Posts",
        cardinality="parent",
        description="The author of this post",
    )


# ---------------------------------------------------------------------------
# Generate ObjectScript source
# ---------------------------------------------------------------------------
# Uncomment to write .cls files:
#
# author_path = schema.write_cls(Author, "./output/cls")
# post_path   = schema.write_cls(Post,   "./output/cls")
# print(author_path, post_path)

# ---------------------------------------------------------------------------
# Print generated ObjectScript to stdout
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Demo.Author ===")
    print(schema.generate_cls(Author))
    print()
    print("=== Demo.Post ===")
    print(schema.generate_cls(Post))
    print()
    print("=== Demo.Author stub ===")
    # Note: stubs.generate_stub() needs IRIS for existing-class introspection,
    # but for registered declared classes it uses the in-memory registry.
    # print(stubs.generate_stub("Demo.Author"))
    print("(run with a live IRIS connection to generate stubs via introspection)")
    print()
    print("CLI usage:")
    print("  python -m iris_orm.schema Demo.Post ./output/cls/")
    print("  python -m iris_orm.schema Demo.Post ./output/cls/ --compile")
    print("  python -m iris_orm.stubs  Demo.Post ./output/python/")
