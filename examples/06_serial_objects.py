"""
06_serial_objects.py — IRISSerial (%SerialObject) usage examples.

%SerialObject classes are embedded/nested objects with no independent identity.
They live inside a parent %Persistent object and are accessed as property values.

Contents
--------
1. Basic Plan C serial definition (Address inside Customer)
2. Schema generation and compilation for serial + parent classes
3. Creating/reading a Customer with a serial Address
4. Nested serials: GeoPoint inside Address
5. Plan A (introspection-first) usage with bind()
"""
from __future__ import annotations
import sys
sys.path.insert(0, "./src/python/")
# ---------------------------------------------------------------------------
# 1. Basic Plan C serial definition
# ---------------------------------------------------------------------------

# Import IRISSerial alongside IRISModel.  Serial classes extend IRISSerial
# instead of IRISModel; everything else (typed annotations, field()) is the same.

from iris_orm import IRISModel, IRISSerial, field, schema

# Define the serial class first — the parent class references it by type.

class Address(IRISSerial):
    """Embedded postal address — stored inside the parent object, not as a separate row."""
    _iris_classname = "Demo.Address"

    Street: str = field(maxlen=200, description="Street line 1")
    City:   str = field(maxlen=100, description="City name")
    State:  str = field(maxlen=2,   description="State / province code")
    Zip:    str = field(maxlen=10,  description="Postal / zip code")


# Parent persistent class references the serial class as a typed annotation.
# IRISMeta detects _iris_serial=True and injects IRISSerialDescriptor automatically.

class Customer(IRISModel):
    """Top-level persistent customer record."""
    _iris_classname = "Demo.Customer"

    Name:    str = field(required=True, maxlen=200, description="Full name")
    Email:   str = field(maxlen=300, description="Contact e-mail")
    Address: Address  # IRISSerialDescriptor is injected here


# ---------------------------------------------------------------------------
# 2. Schema generation and compilation
# ---------------------------------------------------------------------------

def demo_schema_generation() -> None:
    """Generate ObjectScript .cls source for Address and Customer."""
    print("=" * 60)
    print("Schema generation")
    print("=" * 60)

    # Serial class — extends %SerialObject, no Storage block.
    addr_cls = schema.generate_cls(Address)
    print("\n--- Address.cls ---")
    print(addr_cls)

    # Parent class — extends %Persistent, Address property uses IRIS classname as type.
    cust_cls = schema.generate_cls(Customer)
    print("--- Customer.cls ---")
    print(cust_cls)


def demo_write_cls(output_root: str = "/tmp/iris_orm_example") -> None:
    """Write generated .cls files to disk (Address first, then Customer)."""
    addr_path = schema.write_cls(Address, output_root)
    cust_path = schema.write_cls(Customer, output_root)
    print(f"Written: {addr_path}")
    print(f"Written: {cust_path}")


def demo_compile_to_iris() -> None:
    """Compile both classes into a connected IRIS instance (requires live connection)."""
    # Serial class must be compiled first so Customer can reference it.
    schema.compile_to_iris(Address)
    schema.compile_to_iris(Customer)
    print("Address and Customer compiled to IRIS.")


# ---------------------------------------------------------------------------
# 3. Creating and reading a Customer with a serial Address
# ---------------------------------------------------------------------------

def demo_create_customer() -> None:
    """Create a Customer with an embedded Address (requires live IRIS connection)."""
    print("=" * 60)
    print("Creating Customer with Address")
    print("=" * 60)

    # Create a new Customer — a fresh IRIS object is allocated.
    cust = Customer.create(Name="Jane Doe", Email="jane@example.com")

    # Access the embedded Address via the serial descriptor.
    # IRIS automatically allocates the serial sub-object; we just set properties on it.
    addr = cust.Address          # returns an Address instance wrapping the IRIS serial obj
    if addr is not None:
        addr.Street = "123 Main St"
        addr.City   = "Springfield"
        addr.State  = "IL"
        addr.Zip    = "62701"

    cust.save()
    customer_id = cust.pk
    print(f"Saved Customer id={customer_id}")

    # Read back
    loaded = Customer.get(customer_id)
    if loaded is not None:
        print(f"Name: {loaded.Name}")
        loaded_addr = loaded.Address
        if loaded_addr is not None:
            print(f"City: {loaded_addr.City}, State: {loaded_addr.State}")


# ---------------------------------------------------------------------------
# 4. Nested serials: GeoPoint inside Address
# ---------------------------------------------------------------------------

class GeoPoint(IRISSerial):
    """Latitude / longitude pair — nested inside Address."""
    _iris_classname = "Demo.GeoPoint"

    Latitude:  float = field(description="Decimal degrees north/south")
    Longitude: float = field(description="Decimal degrees east/west")


# Address2 extends Address concept with an embedded GeoPoint.
class Address2(IRISSerial):
    """Address with an optional geographic coordinate."""
    _iris_classname = "Demo.Address2"

    Street:   str      = field(maxlen=200)
    City:     str      = field(maxlen=100)
    Location: GeoPoint  # another nested serial descriptor is injected here


class Store(IRISModel):
    """Retail store — persists an Address2 with a GeoPoint."""
    _iris_classname = "Demo.Store"

    Name:     str      = field(required=True, maxlen=200)
    Address:  Address2


def demo_nested_serial_schema() -> None:
    """Show .cls source for nested serial classes."""
    print("=" * 60)
    print("Nested serial schema")
    print("=" * 60)

    print(schema.generate_cls(GeoPoint))
    print(schema.generate_cls(Address2))
    print(schema.generate_cls(Store))


# ---------------------------------------------------------------------------
# 5. Plan A usage with bind()
# ---------------------------------------------------------------------------

class LegacyAddress(IRISSerial):
    """Plan A serial — introspection-first (bind() populates descriptors)."""
    _iris_classname = "Demo.LegacyAddress"
    # No typed annotations here; call bind() after connecting to IRIS.


def demo_plan_a_serial() -> None:
    """
    Demonstrate Plan A (introspection-first) workflow for a serial class.

    After connecting to a live IRIS instance that already has Demo.LegacyAddress
    compiled, call bind() to inject descriptors from %Dictionary.PropertyDefinition.
    """
    print("=" * 60)
    print("Plan A serial bind()")
    print("=" * 60)

    try:
        LegacyAddress.bind()
        print("LegacyAddress descriptors after bind():")
        for name, val in LegacyAddress.__dict__.items():
            if not name.startswith("_"):
                print(f"  {name}: {val!r}")
    except Exception as exc:
        print(f"bind() skipped (no live IRIS connection): {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    demo_schema_generation()
    demo_nested_serial_schema()
    demo_plan_a_serial()

    # These require a live IRIS connection:
    demo_write_cls()
    demo_compile_to_iris()
    demo_create_customer()
