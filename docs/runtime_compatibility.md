# Runtime compatibility matrix

The minimum supported wrapper distribution is `iris-embedded-python-wrapper>=0.5.19`.

| Capability | Embedded-shaped contract | Native-shaped contract |
| --- | --- | --- |
| Object properties and methods | Python proxy attributes/methods | Current `_oref` methods and legacy `_db` dispatch |
| Object identity | normalized `_Id()` | normalized `_Id()` |
| DBAPI ownership | wrapper-created connection is closed | caller connection is proxied and not closed; runtime-created connection is closed |
| Transactions | wrapper transaction functions | same normalized wrapper transaction functions |
| Reference clearing | generated setter then property assignment | generated setter/invoke then native empty-reference assignment |
| Dynamic JSON and streams | class/property operations | native database/object-reference operations |

Both current native object-reference methods and the legacy database-dispatch shape are retained
because they run through the backend contract tests. Transaction rollback retains both
`trollbackone()` and `trollback()` shapes for the same reason.

Unsupported shapes fail through typed runtime errors rather than silently falling through domain
algorithms. Credentials are never included in runtime error context.

Integration coverage runs against the available Embedded matrix in CI. Native deployments should
run the same contract and benchmark gate with their supported server/driver combination before
release.
