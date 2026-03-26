"""
03_relationships.py — One-to-many and parent/child relationships
================================================================

IRIS supports native Relationship properties.  iris_orm maps them to:
  - "parent" / "one"     → returns a single wrapped model instance (or None)
  - "children" / "many"  → returns an IRISRelationshipManager (iterable)

Many-to-many is modelled via an explicit junction class (IRIS has no native M2M).

Assumes these classes are compiled in IRIS (run write_cls + compile_to_iris
or paste into Studio):

    Class Demo.Blog Extends %Persistent { ... }
    Class Demo.Post Extends %Persistent { ... }
    Class Demo.Comment Extends %Persistent { ... }
    Class Demo.Tag Extends %Persistent { ... }
    Class Demo.PostTag Extends %Persistent { ... }   ← M2M junction
"""
from __future__ import annotations

from iris_orm import IRISModel, field, relationship
from iris_orm import schema

# ---------------------------------------------------------------------------
# 1. One-to-many: Blog → Posts
# ---------------------------------------------------------------------------

class Blog(IRISModel):
    _iris_classname = "Demo.Blog"

    Name: str = field(required=True, maxlen=200)

    # "children" = this side holds many Posts
    Posts = relationship("Demo.Post", inverse="Blog", cardinality="children")


class Post(IRISModel):
    _iris_classname = "Demo.Post"

    Title:  str = field(required=True, maxlen=500)
    Body:   str
    Views:  int = field(default=0)

    # "parent" = this side holds a reference to one Blog
    Blog = relationship("Demo.Blog", inverse="Posts", cardinality="parent")

    # "children" = this side holds many Comments
    Comments = relationship("Demo.Comment", inverse="Post", cardinality="children")


class Comment(IRISModel):
    _iris_classname = "Demo.Comment"

    Text:   str = field(required=True)
    Author: str = field(maxlen=100)

    # "parent" = each comment belongs to one Post
    Post = relationship("Demo.Post", inverse="Comments", cardinality="parent")


# ---------------------------------------------------------------------------
# 2. Many-to-many via junction class: Post ↔ Tag
# ---------------------------------------------------------------------------

class Tag(IRISModel):
    _iris_classname = "Demo.Tag"

    Name: str = field(required=True, maxlen=100)

    # Through junction
    PostTags = relationship("Demo.PostTag", inverse="Tag", cardinality="children")


class PostTag(IRISModel):
    """Junction class for Post ↔ Tag many-to-many."""
    _iris_classname = "Demo.PostTag"

    Post = relationship("Demo.Post", inverse="PostTags", cardinality="parent")
    Tag  = relationship("Demo.Tag",  inverse="PostTags", cardinality="parent")


# ---------------------------------------------------------------------------
# 3. Generate all .cls files
# ---------------------------------------------------------------------------

for model in (Blog, Post, Comment, Tag, PostTag):
    path = model.schema.write_cls("./output/cls")
    print(f"Written: {path}")
    model.schema.compile_to_iris()


# ---------------------------------------------------------------------------
# 4. Usage
# ---------------------------------------------------------------------------

# Create blog
blog = Blog(Name="My Tech Blog")
blog.save()

# Create posts linked to blog
p1 = Post(Title="First post", Body="Hello world")
p1.Blog = blog
p1.save()

p2 = Post(Title="Second post", Body="More content")
p2.Blog = blog
p2.save()

# Access children
print(f"\nBlog: {blog.Name!r}")
print(f"Posts ({blog.Posts.count()}):")
for post in blog.Posts:
    print(f"  [{post.pk}] {post.Title!r}")

# Add comments
c1 = Comment(Text="Great post!", Author="Alice")
c1.Post = p1
c1.save()

c2 = Comment(Text="Very helpful", Author="Bob")
c2.Post = p1
c2.save()

print(f"\nComments on '{p1.Title}':")
for comment in p1.Comments:
    print(f"  {comment.Author}: {comment.Text!r}")

# Many-to-many
python_tag = Tag(Name="Python")
python_tag.save()

iris_tag = Tag(Name="IRIS")
iris_tag.save()

pt1 = PostTag()
pt1.Post = p1
pt1.Tag  = python_tag
pt1.save()

pt2 = PostTag()
pt2.Post = p1
pt2.Tag  = iris_tag
pt2.save()

print(f"\nTags on '{p1.Title}':")
for pt in p1.PostTags:
    tag = pt.Tag
    print(f"  #{tag.Name}")

# Navigate from Tag → Posts (via junction)
print(f"\nPosts tagged #{python_tag.Name}:")
for pt in python_tag.PostTags:
    post = pt.Post
    print(f"  [{post.pk}] {post.Title!r}")
