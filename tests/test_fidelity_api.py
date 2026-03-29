from __future__ import annotations

from vei.fidelity import api as fidelity_api
from vei.fidelity.models import TwinFidelityCase


def _case(surface: str, title: str) -> TwinFidelityCase:
    return TwinFidelityCase(
        surface=surface,
        title=title,
        boundary_contract=f"{title} boundary",
        why_it_matters=f"{title} matters",
        status="ok",
        checks=[],
    )


def test_check_vertical_surface_routes_known_verticals(monkeypatch) -> None:
    session = object()
    campaign_case = _case("campaign", "Campaign")
    inventory_case = _case("inventory", "Inventory")
    revenue_case = _case("revenue_graph", "Revenue")
    property_case = _case("property", "Property")

    monkeypatch.setattr(
        fidelity_api, "_check_campaign_surface", lambda _session: campaign_case
    )
    monkeypatch.setattr(
        fidelity_api, "_check_inventory_surface", lambda _session: inventory_case
    )
    monkeypatch.setattr(
        fidelity_api, "_check_revenue_surface", lambda _session: revenue_case
    )
    monkeypatch.setattr(
        fidelity_api, "_check_property_surface", lambda _session: property_case
    )

    assert (
        fidelity_api._check_vertical_surface(session, "digital_marketing_agency")
        is campaign_case
    )
    assert (
        fidelity_api._check_vertical_surface(session, "storage_solutions")
        is inventory_case
    )
    assert fidelity_api._check_vertical_surface(session, "b2b_saas") is revenue_case
    assert (
        fidelity_api._check_vertical_surface(session, " real_estate_management ")
        is property_case
    )


def test_check_vertical_surface_skips_unknown_verticals(monkeypatch) -> None:
    monkeypatch.setattr(
        fidelity_api,
        "_check_property_surface",
        lambda _session: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    case = fidelity_api._check_vertical_surface(object(), "custom_vertical")

    assert case.surface == "property"
    assert case.title == "Vertical surface (skipped)"
    assert case.boundary_contract == (
        "No vertical-specific fidelity check available for this workspace type."
    )
    assert case.why_it_matters == (
        "Vertical fidelity checks are only defined for known vertical types."
    )
    assert case.status == "ok"
    assert case.checks == []
