# SPDX-FileCopyrightText: 2026 H2Lab
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, asdict
from enum import StrEnum, auto
from pathlib import Path, PurePath
from typing import Protocol
import textwrap


@dataclass(frozen=True, kw_only=True, slots=True)
class NinjaVariable:
    key: str
    value: str | PurePath


class NinjaRuleDeps(StrEnum):
    GCC = auto()
    MSVC = auto()


@dataclass(frozen=True, kw_only=True, slots=True)
class NinjaRule:
    name: str
    command: str
    description: str
    depfile: str | None = None
    deps: NinjaRuleDeps | None = None
    generator: bool = False
    pool: str | None = None
    restat: bool = False
    rspfile: str | None = None
    rspfile_content: str | None = None
    msvc_deps_prefix: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class NinjaBuild:
    outputs: Sequence[str | PurePath] = field(default_factory=list)
    rule: str
    inputs: Sequence[str | PurePath | NinjaBuild] = field(default_factory=list)
    implicit: Sequence[str | PurePath | NinjaBuild] = field(default_factory=list)
    validation: Sequence[str | PurePath | NinjaBuild] = field(default_factory=list)
    order_only: Sequence[str | PurePath | NinjaBuild] = field(default_factory=list)
    implicit_outputs: Sequence[str | PurePath] = field(default_factory=list)
    variables: dict[str, str | PurePath | list] = field(default_factory=dict)
    build_by_default: bool = False

    @staticmethod
    def dict_factory(x):
        """
        Generate dict from dataclass.

        Not all fields are relevant while using NinjaBuild dataclass as dict.
        `build_by_default` is used internally at NinjaFile generation to feed
        default targets list if set.

        All others mirror :py:meth:`NinjaWriter.build` arguments.
        """
        exclude_fields = ("build_by_default",)
        return {k: v for (k, v) in x if k not in exclude_fields}

    def asdict(self) -> dict:
        """Return the instance as dictionary using the class defined dict factory."""
        return asdict(self, dict_factory=self.dict_factory)


class NinjaWriter:
    """
    Helper class to generate Ninja build files.

    Provides a high-level API for emitting valid and readable Ninja syntax,
    including support for:

    - variables
    - rules (with validation)
    - pools
    - build statements
    - implicit outputs
    - implicit dependencies
    - order-only dependencies
    - includes and subninja

    Parameters
    ----------
    width : int
        Maximum line width before wrapping (default is 100).

    Notes
    -----
    - Automatically escapes special characters (`$`, space, `:`)
    - Wraps long lines using Ninja continuation (`$`)
    - Validates rule keys against Ninja specification
    """

    _ALLOWED_RULE_KEYS = {
        "command",
        "description",
        "depfile",
        "deps",
        "generator",
        "pool",
        "restat",
        "rspfile",
        "rspfile_content",
        "msvc_deps_prefix",
    }

    _ESCAPE_NEW_LINE = " $"

    def __init__(self, width: int = 100) -> None:
        self.lines: list[str] = []
        self.width = width

    @staticmethod
    def _escape(value: str | PurePath) -> str:
        """
        Escape a value for Ninja syntax.

        Parameters
        ----------
        value : str | PurePath

        Returns
        -------
        str
        """
        return str(value).replace("$", "$$").replace(" ", "$ ").replace(":", "$:")

    def _wrap(self, line: str) -> list[str]:
        """
        Wrap a line if it exceeds the configured width.

        The line is wrapped on the first space that is not escaped in order to keep the generated
        file human readable.

        Parameters
        ----------
        line : str

        Returns
        -------
        list[str]
        """
        if len(line) <= self.width:
            return [line]

        def space_is_escaped(text: str, pos: int) -> bool:
            """Return True if the space at pos in given text is escaped.

            In ninja syntax, space can be escaped (e.g. in windows path) with `$` escape character.
            Note that escape character can be used to escape itself.
            Thus, an escaped space, is a space that is preceded by a odd number of `$`.

            Parameters
            ----------
            text: str
            pos: int

            Returns
            -------
            bool
            """
            idx = pos - 1
            cnt = 0
            while idx > 0 and text[idx] == "$":
                idx -= 1
                cnt += 1
            return cnt % 2 == 1

        def space_pos_before_line_width(text: str) -> int:
            """Return the last unescaped space before line width.

            Parameters
            ----------
            text: str

            Returns
            -------
            int
                unescaped space pos, -1 if not found
            """
            # reverse search from width minus escape sequence
            pos = self.width - len(self._ESCAPE_NEW_LINE)
            while True:
                pos = text.rfind(" ", 0, pos)
                # if pos is negative one, there is no match at all
                # if space is not escaped, there is a match
                # in both case, terminate iteration and return
                # otherwise, look for another space
                if pos < 0 or not space_is_escaped(text, pos):
                    break
            return pos

        def space_pos_after_line_width(text: str) -> int:
            """Return the first unescaped space after line width.

            Parameters
            ----------
            text: str

            Returns
            -------
            int
                unescaped space pos, -1 if not found
            """
            # search from width minus escape sequence
            # extra minus one is hackish here because find will start at previous pos + 1
            pos = self.width - len(self._ESCAPE_NEW_LINE) - 1
            while True:
                pos = text.find(" ", pos + 1)
                # if pos is negative one, there is no match at all
                # if space is not escaped, there is a match
                # in both case, terminate iteration and return
                # otherwise, look for another space
                if pos < 0 or not space_is_escaped(text, pos):
                    break
            return pos

        parts: list[str] = []
        indent: int = len(line) - len(line.lstrip())

        # do not try to wrap on indentation (i.e. leading) space
        min_pos: int = indent

        while len(line) > self.width:
            pos = space_pos_before_line_width(line)
            if pos < min_pos:
                pos = space_pos_after_line_width(line)

            # if a valid position is found, wrap line here
            if pos >= min_pos:
                parts.append(line[:pos] + self._ESCAPE_NEW_LINE)
                # update remaining text to wrap w/ extra indentation
                line = " " * (indent + 2) + line[pos + 1 :]
                # wrapped line are indented
                min_pos = indent + 2
            else:
                # if pos negative, the remaining cannot be wrapped
                break

        parts.append(line)
        return parts

    def _write(self, text: str = "") -> None:
        for line in self._wrap(text):
            self.lines.append(line)

    def comment(self, text: str) -> None:
        """
        Add a comment block.

        Parameters
        ----------
        text : str
        """
        wrapped_comment = textwrap.wrap(
            text, self.width - 2, break_long_words=False, break_on_hyphens=False
        )
        for line in wrapped_comment:
            self.lines.append(f"# {line}")

    def variable(self, key: str, value: str | PurePath) -> None:
        """
        Declare a Ninja variable.

        Parameters
        ----------
        key : str
        value : str | PurePath
        """
        self._write(f"{key} = {self._escape(value)}")

    def pool(self, name: str, depth: int) -> None:
        """
        Declare a Ninja pool.

        Parameters
        ----------
        name : str
            Pool name.
        depth : int
            Maximum parallel jobs.

        Raises
        ------
        ValueError
            If depth <= 0.
        """
        if depth <= 0:
            raise ValueError("Pool depth must be > 0")

        self._write(f"pool {name}")
        self._write(f"  depth = {depth}")
        self._write()

    def rule(self, name: str, **kwargs: str) -> None:
        """
        Declare a Ninja rule with validation.

        Parameters
        ----------
        name : str
        **kwargs : str
            Rule attributes.

        Raises
        ------
        ValueError
            If invalid rule keys are provided.
        """
        invalid = set(kwargs) - self._ALLOWED_RULE_KEYS
        if invalid:
            raise ValueError(
                f"Invalid Ninja rule keys: {invalid}. "
                f"Allowed keys: {sorted(self._ALLOWED_RULE_KEYS)}"
            )

        self._write(f"rule {name}")
        for k, v in kwargs.items():
            if isinstance(v, bool) and v:
                self._write(f"  {k} = 1")
            elif v:
                self._write(f"  {k} = {v}")
        self._write()

    def build(
        self,
        outputs: list[str | PurePath],
        rule: str,
        inputs: list[str | PurePath | dict] | None = None,
        implicit: list[str | PurePath | dict] | None = None,
        order_only: list[str | PurePath | dict] | None = None,
        validation: list[str | PurePath | dict] | None = None,
        implicit_outputs: list[str | PurePath] | None = None,
        variables: dict[str, str | PurePath | list] | None = None,
    ) -> None:
        """
        Declare a Ninja build statement.

        Parameters
        ----------
        outputs : list[str | PurePath]
            Explicit outputs.
        rule : str
            Rule name.
        inputs : list[str | PurePath | dict] | None
            Explicit inputs.
        implicit : list[str | PurePath | dict] | None
            Implicit dependencies (after `|`).
        order_only : list[str | PurePath | dict] | None
            Order-only dependencies (after `||`).
        validation : list[str | PurePath | dict] | None
            Validation dependencies (after `|@`)
        implicit_outputs : list[str | PurePath] | None
            Additional outputs (after `|`, before `:`).
        variables : dict[str, str | PurePath | list] | None
            Per-build variables.

        Note
        ----
        NinjaWrite is used internally by NinjaFile which unpack NinjaBuild dataclass with `**asdict`
        asdict will recursively convert dataclass as dictionary and thus input deps as well.
        Here, the right type for such a input deps is list[ str | PurePath | dict ].
        The given dict is 'pack' as a NinjaBuild dataclass while formatted.
        """

        def _format(elements: list[str | PurePath | dict]) -> list[str]:
            data: list[str] = []
            for elem in elements:
                if isinstance(elem, dict):
                    data.extend([self._escape(x) for x in NinjaBuild(**elem).outputs])
                else:
                    data.append(self._escape(elem))
            return data

        out = [self._escape(x) for x in outputs]
        inp: list[str] = []

        if inputs:
            inp.extend(_format(inputs))

        if implicit:
            inp.append("|")
            inp.extend(_format(implicit))

        if order_only:
            inp.append("||")
            inp.extend(_format(order_only))

        if validation:
            inp.append("|@")
            inp.extend(_format(validation))

        if implicit_outputs:
            out.append("|")
            out.extend([self._escape(x) for x in implicit_outputs])

        self._write(f"build {' '.join(out)}: {rule} {' '.join(inp)}")

        if variables:
            for k, v in variables.items():
                if isinstance(v, list):
                    print(v)
                    self._write(f"  {k} = {' '.join([self._escape(elem) for elem in v])}")
                else:
                    self._write(f"  {k} = {self._escape(v)}")

        self._write()

    def include(self, path: PurePath) -> None:
        """
        Include another Ninja file.

        Parameters
        ----------
        path : PurePath
        """
        self._write(f"include {self._escape(path)}")

    def subninja(self, path: PurePath) -> None:
        """
        Include a subninja file.

        Parameters
        ----------
        path : PurePath
        """
        self._write(f"subninja {self._escape(path)}")

    def default(self, targets: Sequence[str | PurePath]) -> None:
        """
        Define default build target(s).

        Parameters
        ----------
        targets : Sequence[str | PurePath]

        Raises
        ------
        ValueError
            Id targets is empty.
        """
        if len(targets) == 0:
            raise ValueError("empty default build targets")
        self._write(f"default {' '.join([self._escape(t) for t in targets])}")

    def newline(self) -> None:
        """Insert an empty line."""
        self._write()

    def render(self) -> str:
        """
        Render the Ninja file.

        Note
        ----
        The rendered string ends with a newline characters in order to be Posix text file compliant

        Returns
        -------
        str
        """
        return "\n".join(self.lines) + "\n"


class NinjaVariablesProtocol(Protocol):
    """Protocol for ninja variable builder."""

    @classmethod
    def __ninja_variables__(cls) -> Iterator[NinjaVariable]:
        """Ninja variables generator.

        Yields
        ------
        NinjaVariable
            The next ninja variable

        Note
        ----
            Default implementation is an empty generator
        """
        yield from ()


class NinjaRulesProtocol(Protocol):
    """Protocol for ninja rules builder."""

    @classmethod
    def __ninja_rules__(cls) -> Iterator[NinjaRule]:
        """Ninja rules generator.

        Yields
        ------
        NinjaRule
            The next ninja rule

        Note
        ----
            Default implementation is an empty generator
        """
        yield from ()


class NinjaBuildsProtocol(Protocol):
    """Protocol for ninja build builder."""

    def __ninja_builds__(self) -> Iterator[NinjaBuild]:
        """Ninja build generator.

        Yields
        ------
        NinjaBuild
            The next ninja build

        Note
        ----
            Default implementation is an empty generator
        """
        yield from ()


class NinjaBuilderProtocol(
    NinjaVariablesProtocol, NinjaRulesProtocol, NinjaBuildsProtocol, Protocol
):
    """
    Protocol for Ninja builders.

    Ninja builders (e.g. Package builder or internal build step) are likely implementing
    all previous builder protocol (i.e. Variables, Rules and Builds).
    """

    @property
    def name(self) -> str: ...


class NinjaFile:
    """
    Orchestrates Ninja file generation.

    Parameters
    ----------
    builders : list[NinjaBuilderProtocol]
        Builder instances.
    """

    def __init__(self, builders: list[NinjaBuilderProtocol]) -> None:
        self.builders = builders
        self.types: set[type[NinjaBuilderProtocol]] = set()
        self._validate()

    def _validate(self) -> None:
        """Validate ninja file builders.

        Raises
        ------
        ValueError
            If duplicate builder names exist.
        """
        seen: set[str] = set()
        for b in self.builders:
            if b.name in seen:
                raise ValueError(f"Duplicate builder name: {b.name}")
            if type(b) not in self.types:
                self.types.add(type(b))
            seen.add(b.name)

    def _collect_rules(self) -> list[NinjaRule]:
        """
        Collect and validate Ninja rules across builder types.

        It is an error to have duplicate rule name.
        Error is silenced if rules are identical.

        Returns
        -------
        list[NinjaRule]

        Raises
        ------
        ValueError
            If duplicate rule names are detected.
        """
        rules: dict[str, NinjaRule] = {}

        for t in self.types:
            for rule in t.__ninja_rules__():
                if rule.name in rules:
                    if asdict(rules[rule.name]) != asdict(rule):
                        raise ValueError(
                            f"Duplicate Ninja rule detected: '{rule.name}' from {t.__name__}"
                        )
                    continue
                rules[rule.name] = rule

        return list(rules.values())

    def generate(self) -> str:
        """
        Generate Ninja file content.

        Returns
        -------
        str
        """
        nw = NinjaWriter()

        nw.comment("Generated by Barbican Ninja File builder")
        nw.comment("** DO NOT EDIT **")
        nw.newline()

        for v in [v for t in self.types for v in t.__ninja_variables__()]:
            nw.variable(**asdict(v))
        nw.newline()

        for r in self._collect_rules():
            nw.rule(**asdict(r))
        nw.newline()

        default_targets: list[str | PurePath] = []
        for b in [b for builder in self.builders for b in builder.__ninja_builds__()]:
            nw.build(**(b.asdict()))
            if b.build_by_default:
                default_targets.extend(b.outputs)
        nw.newline()

        if default_targets:
            nw.default(default_targets)

        return nw.render()

    def write(self, path: Path = Path("build.ninja")) -> None:
        """
        Write Ninja file.

        Parameters
        ----------
        path : Path
        """
        path.write_text(self.generate(), encoding="utf-8")
