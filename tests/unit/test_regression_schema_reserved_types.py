import pytest
from mnemobun.core import schema
from mnemobun.core.errors import ValidationError


@pytest.mark.parametrize("type_name", ["archive", "schemas", "dream-reports"])
def test_schema_type_cannot_occupy_reserved_storage(store, type_name):
    custom = schema.MemorySchema(type_name, "Useful custom type", ("subject",))
    with pytest.raises(ValidationError):
        schema.validate(custom, store.config)
