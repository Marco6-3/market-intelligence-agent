from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from .utils.text import clean_text


DEFAULT_THEME_ALIASES: dict[str, list[str]] = {
    "HBM": ["HBM", "high-bandwidth memory", "high bandwidth memory", "High Bandwidth Memory"],
    "HBM3E": ["HBM3E", "HBM 3E"],
    "HBM4": ["HBM4", "HBM 4"],
    "DRAM": ["DRAM", "dynamic random access memory"],
    "NAND": ["NAND", "NAND Flash", "flash memory"],
    "HDD": ["HDD", "hard disk drive", "nearline HDD", "nearline drive", "mass capacity storage"],
    "AI data center": [
        "AI data center",
        "AI datacenter",
        "cloud AI infrastructure",
        "hyperscale AI",
        "AI cloud",
        "data center capex",
    ],
    "AI ASIC": ["AI ASIC", "custom AI chip", "custom silicon", "hyperscaler ASIC"],
    "AI networking": [
        "AI networking",
        "Ethernet AI fabric",
        "data center switching",
        "optical interconnect",
    ],
    "Advanced packaging": ["advanced packaging", "CoWoS", "chiplet", "2.5D packaging", "3D packaging"],
    "EUV": ["EUV", "High-NA EUV", "lithography"],
    "Robotics": [
        "robotics",
        "robot",
        "humanoid robot",
        "embodied AI",
        "physical AI",
        "cobot",
        "collaborative robot",
        "AMR",
        "autonomous mobile robot",
    ],
    "Surgical robotics": ["surgical robot", "robotic surgery", "da Vinci"],
    "Industrial automation": [
        "factory automation",
        "industrial automation",
        "smart manufacturing",
        "servo",
        "machine vision",
    ],
}


@dataclass(frozen=True)
class ThemeMatch:
    theme: str
    matched_terms: list[str]


def load_theme_aliases(path: Path | None = None) -> dict[str, list[str]]:
    if path is None:
        path = Path.cwd() / "config" / "theme_aliases.yaml"
    if not path.exists():
        return DEFAULT_THEME_ALIASES
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return DEFAULT_THEME_ALIASES
    themes = data.get("themes")
    if not isinstance(themes, dict):
        return DEFAULT_THEME_ALIASES
    aliases: dict[str, list[str]] = {}
    for theme, payload in themes.items():
        if isinstance(payload, dict):
            raw_aliases = payload.get("aliases", [])
        else:
            raw_aliases = payload
        if not isinstance(raw_aliases, list):
            continue
        values = [clean_text(value) for value in raw_aliases]
        clean_values = [value for value in values if value]
        if clean_values:
            aliases[str(theme)] = clean_values
    return aliases or DEFAULT_THEME_ALIASES


def match_theme_aliases(
    title: object,
    summary: object = None,
    *,
    aliases: dict[str, list[str]] | None = None,
    extra_terms: Iterable[str] = (),
) -> list[ThemeMatch]:
    alias_map = aliases or DEFAULT_THEME_ALIASES
    haystack = _normalize_for_match(f"{title or ''} {summary or ''}")
    matches: list[ThemeMatch] = []
    for theme, terms in alias_map.items():
        matched_terms: list[str] = []
        seen: set[str] = set()
        for term in terms:
            normalized = _normalize_for_match(term)
            if not normalized:
                continue
            if _contains_term(haystack, normalized):
                key = clean_text(term).casefold()
                if key not in seen:
                    seen.add(key)
                    matched_terms.append(clean_text(term) or str(term))
        if matched_terms:
            matches.append(ThemeMatch(theme=theme, matched_terms=matched_terms))

    for term in extra_terms:
        cleaned = clean_text(term)
        if not cleaned:
            continue
        normalized = _normalize_for_match(cleaned)
        if not _contains_term(haystack, normalized):
            continue
        if any(match.theme.casefold() == cleaned.casefold() for match in matches):
            continue
        matches.append(ThemeMatch(theme=cleaned, matched_terms=[cleaned]))
    return matches


def related_themes_and_terms(
    title: object,
    summary: object = None,
    *,
    aliases: dict[str, list[str]] | None = None,
    extra_terms: Iterable[str] = (),
) -> tuple[list[str], list[str]]:
    matches = match_theme_aliases(title, summary, aliases=aliases, extra_terms=extra_terms)
    related: list[str] = []
    terms: list[str] = []
    seen_related: set[str] = set()
    seen_terms: set[str] = set()
    for match in matches:
        theme_key = match.theme.casefold()
        if theme_key not in seen_related:
            seen_related.add(theme_key)
            related.append(match.theme)
        for term in match.matched_terms:
            term_key = term.casefold()
            if term_key in seen_terms:
                continue
            seen_terms.add(term_key)
            terms.append(term)
    return related, terms


def _normalize_for_match(value: object) -> str:
    text = clean_text(value) or ""
    text = text.casefold()
    text = re.sub(r"[-_/]+", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff.]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _contains_term(haystack: str, normalized_term: str) -> bool:
    if not normalized_term:
        return False
    if re.search(r"[\u4e00-\u9fff]", normalized_term):
        return normalized_term in haystack
    return re.search(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", haystack) is not None
