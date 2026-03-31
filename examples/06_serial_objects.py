"""
06_serial_objects.py — Declared serial objects with the explicit session.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from iris_orm import IRISModel, IRISSerial, Registry, field

from examples._common import bind_session, sync_registry


class Address(IRISSerial):
    _iris_classname = "Demo.Address"

    City: str = field(maxlen=100)
    Zip: str = field(maxlen=10)


class Customer(IRISModel):
    _iris_classname = "Demo.Customer"

    Name: str = field(required=True, maxlen=200)
    Address: Address


def main() -> None:
    registry = Registry()
    registry.register(Address)
    registry.register(Customer)

    adapter = sync_registry(registry)
    _adapter, _binder, session = bind_session(registry, adapter=adapter)

    customer = Customer(Name="Jane Doe", Address=Address(City="Paris", Zip="75001"))
    session.add(customer)
    session.commit()

    loaded = session.get(Customer, customer.pk)
    print("Customer:", loaded.Name)
    print("City:", loaded.Address.City if loaded.Address is not None else None)


if __name__ == "__main__":
    main()
