# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0


from collections.abc import Mapping

from jsonschema import Draft202012Validator

from . import REGISTRY


def _validate(config: Mapping, schema_uri: str) -> None:
    schema = REGISTRY.contents(schema_uri)
    validator = Draft202012Validator(schema, registry=REGISTRY)
    validator.validate(config)


def validate_project_config(config: Mapping) -> None:
    _validate(config, "urn:barbican:project")


def validate_sdk_config(config: Mapping) -> None:
    _validate(config, "urn:barbican:sdk")
