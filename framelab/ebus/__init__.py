"""Core eBUS snapshot parsing, catalog, and compare helpers."""

from .canonical import (
    EbusCanonicalFieldResolution,
    EbusCanonicalResolutionSet,
    apply_ebus_canonical_baseline,
    coerce_ebus_value_for_spec,
    resolve_ebus_canonical_fields,
)
from .catalog import (
    ebus_catalog_config_path,
    ebus_catalog_index,
    ebus_to_canonical_index,
    load_ebus_catalog,
    mapped_datacard_key_for_ebus,
)
from .compare import compare_effective_configs, compare_raw_snapshots
from .effective import (
    describe_ebus_source,
    discover_effective_ebus_snapshot_path,
    ebus_enabled,
    ebus_enabled_for_acquisition,
    effective_ebus_parameters,
    load_ebus_override_map,
    load_ebus_override_map_from_acquisition,
)
from .models import (
    EbusCatalogEntry,
    EbusCompareEntry,
    EbusEffectiveParameter,
    EbusParameter,
    EbusSnapshot,
    EbusSourceDescriptor,
)
from .parser import parse_ebus_config
from .sidecar import (
    ACQUISITION_EBUS_CONFIG_NAME,
    EBUS_PARSE_VERSION,
    attached_ebus_config_path,
    discover_ebus_snapshot_path,
    file_sha256,
    has_attached_ebus_config,
)

__all__ = [
    "ACQUISITION_EBUS_CONFIG_NAME",
    "EBUS_PARSE_VERSION",
    "EbusCatalogEntry",
    "EbusCanonicalFieldResolution",
    "EbusCanonicalResolutionSet",
    "EbusCompareEntry",
    "EbusEffectiveParameter",
    "EbusParameter",
    "EbusSnapshot",
    "EbusSourceDescriptor",
    "apply_ebus_canonical_baseline",
    "attached_ebus_config_path",
    "coerce_ebus_value_for_spec",
    "compare_effective_configs",
    "compare_raw_snapshots",
    "describe_ebus_source",
    "discover_effective_ebus_snapshot_path",
    "discover_ebus_snapshot_path",
    "ebus_enabled",
    "ebus_enabled_for_acquisition",
    "ebus_catalog_config_path",
    "ebus_catalog_index",
    "ebus_to_canonical_index",
    "effective_ebus_parameters",
    "file_sha256",
    "has_attached_ebus_config",
    "load_ebus_catalog",
    "load_ebus_override_map",
    "load_ebus_override_map_from_acquisition",
    "mapped_datacard_key_for_ebus",
    "parse_ebus_config",
    "resolve_ebus_canonical_fields",
]
