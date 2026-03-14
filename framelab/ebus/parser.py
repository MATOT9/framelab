"""Parser for eBUS Player ``.pvcfg`` snapshot files."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
from typing import Any

from .models import EbusParameter, EbusSnapshot
from .catalog import ebus_catalog_index


def _normalize_value(raw_value: str) -> tuple[Any, str]:
    """Infer a stable normalized value and type from a raw string."""
    text = raw_value.strip()
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return (lowered == "true", "bool")
    if lowered in {"on", "off"}:
        return (lowered == "on", "bool")
    if lowered in {"0", "1"}:
        return (lowered == "1", "bool")
    if text:
        try:
            integer = int(text, 10)
        except Exception:
            integer = None
        else:
            return (integer, "int")
        try:
            number = float(text)
        except Exception:
            pass
        else:
            return (number, "float")
    return (raw_value, "string")


def _parameter_record(
    *,
    section: str,
    name: str,
    raw_value: str,
    catalog_index: dict[str, Any],
) -> EbusParameter:
    """Build one normalized parameter record."""
    qualified_key = f"{section}.{name}"
    normalized_value, normalized_type = _normalize_value(raw_value)
    return EbusParameter(
        qualified_key=qualified_key,
        section=section,
        name=name,
        raw_value=raw_value,
        normalized_value=normalized_value,
        normalized_type=normalized_type,
        catalog_entry=catalog_index.get(qualified_key),
    )


def _parse_parameter_nodes(
    parent: ET.Element,
    *,
    section: str,
    catalog_index: dict[str, Any],
) -> list[EbusParameter]:
    """Parse direct ``parameter`` children under one section node."""
    parameters: list[EbusParameter] = []
    for parameter in parent.findall("parameter"):
        name = str(parameter.attrib.get("name", "")).strip()
        if not name:
            continue
        raw_value = (parameter.text or "").strip()
        parameters.append(
            _parameter_record(
                section=section,
                name=name,
                raw_value=raw_value,
                catalog_index=catalog_index,
            ),
        )
    return parameters


def parse_ebus_config(path: str | Path) -> EbusSnapshot:
    """Parse an eBUS Player ``.pvcfg`` file into a normalized snapshot."""
    source_path = Path(path)
    root = ET.fromstring(source_path.read_text(encoding="utf-8"))
    format_version = str(root.attrib.get("version", "")).strip() or "1.0"
    catalog_index = ebus_catalog_index()

    parameters: list[EbusParameter] = []
    sections: list[str] = []
    seen_sections: set[str] = set()

    def _register_section(section: str) -> None:
        if section not in seen_sections:
            seen_sections.add(section)
            sections.append(section)

    for element in root:
        tag = element.tag.strip().lower()
        if tag == "context":
            name = str(element.attrib.get("name", "")).strip()
            if not name:
                continue
            section = "context"
            _register_section(section)
            parameters.append(
                _parameter_record(
                    section=section,
                    name=name,
                    raw_value=(element.text or "").strip(),
                    catalog_index=catalog_index,
                ),
            )
            continue

        if tag == "propertylist":
            list_name = str(element.attrib.get("name", "")).strip()
            if not list_name:
                continue
            section = f"propertylist.{list_name}"
            _register_section(section)
            parameters.extend(
                _parse_parameter_nodes(
                    element,
                    section=section,
                    catalog_index=catalog_index,
                ),
            )
            continue

        if tag == "genparameterarray":
            array_name = str(element.attrib.get("name", "")).strip()
            if not array_name:
                continue
            section = f"genparameterarray.{array_name}"
            _register_section(section)
            parameters.extend(
                _parse_parameter_nodes(
                    element,
                    section=section,
                    catalog_index=catalog_index,
                ),
            )
            continue

        if tag == "device":
            section = "device"
            _register_section(section)
            device_node = element.find("device")
            if device_node is not None:
                parameters.extend(
                    _parse_parameter_nodes(
                        device_node,
                        section=section,
                        catalog_index=catalog_index,
                    ),
                )
            communication_node = element.find("communication")
            if communication_node is not None:
                comm_section = "device.communication"
                _register_section(comm_section)
                parameters.extend(
                    _parse_parameter_nodes(
                        communication_node,
                        section=comm_section,
                        catalog_index=catalog_index,
                    ),
                )
            continue

        if tag == "stream":
            section = "stream"
            _register_section(section)
            parameters_node = element.find("parameters")
            if parameters_node is not None:
                parameters.extend(
                    _parse_parameter_nodes(
                        parameters_node,
                        section=section,
                        catalog_index=catalog_index,
                    ),
                )

    return EbusSnapshot(
        source_path=source_path,
        format_version=format_version,
        parameters=tuple(parameters),
        sections=tuple(sections),
    )
