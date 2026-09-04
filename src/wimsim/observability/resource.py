"""The OTel resource: what every signal from this process says about where it came from.

One module because traces, metrics and logs must agree. The collector is configured with
``resource_to_telemetry_conversion``, so these attributes become Prometheus labels, become Tempo
process tags, and become Loki stream labels -- and a dashboard that filters `station_id` on one
signal and not another is a dashboard whose panels quietly disagree with each other.

``station_id`` is deliberately a resource attribute rather than a per-measurement one. A process
serves exactly one station; carrying it per point would multiply cardinality for no information.
"""

from __future__ import annotations

from wimsim import __version__

SERVICE_NAME = "wimsim-edge"

__all__ = ["SERVICE_NAME", "build_resource", "resource_attributes"]


def resource_attributes(
    *,
    station_id: str,
    run_id: str | None = None,
    service_name: str = SERVICE_NAME,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """The attribute dict, as plain data so it can be asserted on without the SDK installed."""
    attrs = {
        "service.name": service_name,
        "service.version": __version__,
        "station_id": station_id,
    }
    if run_id:
        attrs["run_id"] = run_id
    if extra:
        attrs.update({k: str(v) for k, v in extra.items()})
    return attrs


def build_resource(
    *,
    station_id: str,
    run_id: str | None = None,
    service_name: str = SERVICE_NAME,
    extra: dict[str, str] | None = None,
):
    """The SDK object. Imports the SDK, so only call it when a collector is configured."""
    from opentelemetry.sdk.resources import Resource

    return Resource.create(
        resource_attributes(
            station_id=station_id, run_id=run_id, service_name=service_name, extra=extra
        )
    )
