# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

"""Sphinx directives for JSON Schema documentation.

Provides
--------
- ``SchemaTocDirective``: generates a table of contents listing all schemas.
"""

from __future__ import annotations

import importlib
import typing

from docutils import nodes
from docutils.statemachine import StringList
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective
from sphinx.util.nodes import nested_parse_with_titles

from .renderer import derive_title, discover_schema_uris

if typing.TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SchemaTocDirective(SphinxDirective):
    """Generate a table of contents listing all JSON schemas.

    The directive discovers schema URIs from the configured registry module
    and emits a definition list with cross-reference links.

    Usage::

        .. schematoc::

    Options::

    :exclude: str
        Comma-separated list of URNs to exclude from the listing.
    """

    has_content = False
    required_arguments = 0
    optional_arguments = 0
    option_spec: typing.ClassVar[dict[str, typing.Any]] = {
        "exclude": lambda x: [s.strip() for s in x.split(",")],
    }

    def run(self) -> list[nodes.Node]:
        """Execute the directive and return docutils nodes.

        Returns
        -------
        list[nodes.Node]
            A parsed RST definition list of schema links.
        """
        registry_module = self.env.config.jsonschema_registry_module
        registry_attr = self.env.config.jsonschema_registry_attr

        try:
            uris = discover_schema_uris(registry_module)
        except Exception as exc:
            logger.warning(
                "schematoc: failed to discover schemas: %s",
                exc,
                location=self.get_location(),
                type="jsonschema",
                subtype="toc",
            )
            return []

        exclude = set(self.options.get("exclude", []))
        uris = [u for u in uris if u not in exclude]

        if not uris:
            return []

        # Load registry for descriptions
        try:
            mod = importlib.import_module(registry_module)
            registry = getattr(mod, registry_attr)
        except Exception:
            registry = None

        # Build RST lines for the definition list
        rst_lines: list[str] = []
        for uri in uris:
            title = derive_title(uri)

            description = ""
            if registry is not None:
                try:
                    schema = registry.contents(uri)
                    description = schema.get("description", "")
                except Exception:
                    pass

            rst_lines.append(f":schema:`{title} <{uri}>`")
            if description:
                rst_lines.append(f"   {description}")
            else:
                rst_lines.append(f"   Schema ``{uri}``")
            rst_lines.append("")

        # Parse the RST into docutils nodes
        vl = StringList(rst_lines, source=self.get_location())
        node = nodes.section()
        node.document = self.state.document
        nested_parse_with_titles(self.state, vl, node)
        return node.children
