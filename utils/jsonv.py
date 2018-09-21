from jsonschema import validate as v, ValidationError


def validate(json, schema):
    try:
        v(json, schema)
        return True
    except ValidationError:
        return False
