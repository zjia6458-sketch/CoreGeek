# FortressAgent V0.3.5 — Python 3.11 Compatibility

The competition runtime baseline is **Python 3.11.x**.

## Dataclass default rule

Do not write unhashable container-like objects directly as dataclass defaults.
In particular, this is forbidden:

```python
weapon_shop: Mapping[str, float] = MappingProxyType({})
```

Python 3.11 raises during class creation:

```text
ValueError: mutable default <class 'mappingproxy'> for field ... is not allowed: use default_factory
```

Use a factory instead:

```python
from dataclasses import dataclass, field
from types import MappingProxyType

weapon_shop: Mapping[str, float] = field(
    default_factory=lambda: MappingProxyType({})
)
```

The same rule is applied to:

```text
GameState.weapon_shop
GameState.last_round_role_action_results
```

## Version contract

`pyproject.toml` declares:

```toml
requires-python = "==3.11.*"
```

The test suite also parses every production `.py` source using the Python 3.11
grammar and rejects direct `MappingProxyType(...)` dataclass defaults.
