import re
from string import Formatter


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(template: str, **kwargs) -> str:
    """Fill {variable} slots. Missing keys left as-is. No f-strings in callers."""
    # Use format_map with SafeDict so partial templates work
    return template.format_map(
        _SafeDict(**{k: ("" if v is None else v) for k, v in kwargs.items()})
    )
