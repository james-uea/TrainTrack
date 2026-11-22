"""
Print the API's OpenAPI schema, which the web front end's TypeScript types are generated from.

    uv run src/api_schema.py > web/openapi.json   (or `pnpm gen:api` in web/)
"""

import json

from api import create_app


def schema() -> dict:
    return create_app().openapi()


if __name__ == "__main__":
    print(json.dumps(schema(), indent=2))
