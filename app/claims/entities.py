import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EntityDefinition:
    canonical_name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EntityResolution:
    canonical_name: str
    basis: str
    matched_aliases: tuple[str, ...] = ()
    ambiguous_candidates: tuple[str, ...] = ()


ENTITY_DEFINITIONS: tuple[EntityDefinition, ...] = (
    EntityDefinition(
        canonical_name="Reserve Bank of India",
        aliases=("Reserve Bank of India", "RBI"),
    ),
    EntityDefinition(
        canonical_name="Securities and Exchange Board of India",
        aliases=("Securities and Exchange Board of India", "SEBI"),
    ),
    EntityDefinition(
        canonical_name="National Stock Exchange of India",
        aliases=("National Stock Exchange of India", "National Stock Exchange", "NSE India", "NSE"),
    ),
    EntityDefinition(
        canonical_name="Ministry of Statistics and Programme Implementation",
        aliases=(
            "Ministry of Statistics and Programme Implementation",
            "Ministry of Statistics & Programme Implementation",
            "MoSPI",
        ),
    ),
    EntityDefinition(
        canonical_name="World Bank",
        aliases=("World Bank", "The World Bank"),
    ),
    EntityDefinition(
        canonical_name="International Monetary Fund",
        aliases=("International Monetary Fund", "IMF"),
    ),
)


def _normalized(value: str) -> str:
    return " ".join(value.split()).strip().lower()


def _alias_pattern(alias: str) -> re.Pattern[str]:
    # Word-like boundaries prevent short aliases such as RBI/IMF/NSE from
    # matching inside unrelated longer tokens. Spaces remain flexible because
    # extracted HTML/PDF text can contain repeated whitespace.
    pieces = [re.escape(piece) for piece in alias.split()]
    body = r"\s+".join(pieces)
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.IGNORECASE)


def _canonicalize_default(default_entity: str) -> str:
    normalized_default = _normalized(default_entity)
    for definition in ENTITY_DEFINITIONS:
        names = (definition.canonical_name, *definition.aliases)
        if normalized_default in {_normalized(name) for name in names}:
            return definition.canonical_name
    return " ".join(default_entity.split()).strip()


def resolve_entity(text: str, *, default_entity: str) -> EntityResolution:
    """Resolve a known canonical subject only when local evidence is explicit.

    Phase 3 intentionally avoids broad NER or inference. A non-default entity is
    assigned only when the local evidence contains an exact known name/alias and
    exactly one canonical entity is represented. If multiple known entities are
    present, the source/default entity is retained rather than guessing which one
    the metric belongs to.
    """
    canonical_default = _canonicalize_default(default_entity)
    matches: dict[str, set[str]] = {}

    for definition in ENTITY_DEFINITIONS:
        for alias in definition.aliases:
            if _alias_pattern(alias).search(text):
                matches.setdefault(definition.canonical_name, set()).add(alias)

    if len(matches) == 1:
        canonical_name, aliases = next(iter(matches.items()))
        return EntityResolution(
            canonical_name=canonical_name,
            basis="explicit_local_alias",
            matched_aliases=tuple(sorted(aliases, key=str.lower)),
        )

    if len(matches) > 1:
        return EntityResolution(
            canonical_name=canonical_default,
            basis="ambiguous_local_entities_defaulted",
            ambiguous_candidates=tuple(sorted(matches)),
        )

    return EntityResolution(
        canonical_name=canonical_default,
        basis="source_default",
    )
