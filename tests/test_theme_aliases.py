from market_agent.theme_aliases import related_themes_and_terms


def test_high_bandwidth_memory_matches_hbm() -> None:
    themes, terms = related_themes_and_terms("high-bandwidth memory demand rises")

    assert "HBM" in themes
    assert "high-bandwidth memory" in terms


def test_high_bandwidth_memory_case_and_space_matches_hbm() -> None:
    themes, terms = related_themes_and_terms("High Bandwidth Memory supply remains tight")

    assert "HBM" in themes
    assert any(term.casefold() == "high bandwidth memory" for term in terms)


def test_ai_datacenter_matches_ai_data_center() -> None:
    themes, _ = related_themes_and_terms("AI datacenter capex keeps rising")

    assert "AI data center" in themes


def test_custom_ai_chip_matches_ai_asic() -> None:
    themes, _ = related_themes_and_terms("Hyperscaler custom AI chip project expands")

    assert "AI ASIC" in themes


def test_collaborative_robot_matches_robotics() -> None:
    themes, _ = related_themes_and_terms("collaborative robot demand improves")

    assert "Robotics" in themes
