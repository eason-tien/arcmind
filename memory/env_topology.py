# -*- coding: utf-8 -*-
"""
ArcMind — Environment Topology Memory
========================================
持久化三維度認知掃描結果，提供壓縮摘要給 OODA Observe 階段。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

logger = logging.getLogger("arcmind.memory.env_topology")


def update_topology(layer: str, data: dict) -> None:
    """Update topology data for a layer (L1/L2/L3)."""
    try:
        from db.schema import EnvTopology_, SessionLocal
        db = SessionLocal()
        try:
            # Upsert per layer
            existing = db.query(EnvTopology_).filter_by(layer=layer).first()
            if existing:
                existing.data = json.dumps(data, ensure_ascii=False, default=str)
                existing.category = _layer_category(layer)
                existing.updated_at = datetime.utcnow()
            else:
                entry = EnvTopology_(
                    layer=layer,
                    category=_layer_category(layer),
                    data=json.dumps(data, ensure_ascii=False, default=str),
                )
                db.add(entry)
            db.commit()
            logger.info("[Topology] Updated %s", layer)
        finally:
            db.close()
    except Exception as e:
        logger.error("[Topology] Update failed: %s", e)


def get_topology(layer: str = "") -> dict:
    """Get topology data for a specific layer, or all."""
    try:
        from db.schema import EnvTopology_, SessionLocal
        db = SessionLocal()
        try:
            if layer:
                row = db.query(EnvTopology_).filter_by(layer=layer).first()
                if row:
                    return {
                        "layer": row.layer,
                        "data": json.loads(row.data or "{}"),
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    }
                return {"layer": layer, "data": {}, "updated_at": None}
            else:
                rows = db.query(EnvTopology_).all()
                return {
                    row.layer: {
                        "data": json.loads(row.data or "{}"),
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    }
                    for row in rows
                }
        finally:
            db.close()
    except Exception as e:
        logger.error("[Topology] Read failed: %s", e)
        return {}


def get_topology_summary() -> str:
    """
    返回壓縮環境摘要（< 300 tokens），注入 OODA Observe 階段。
    """
    try:
        all_data = get_topology()
        if not all_data:
            return ""

        lines = ["[Environment Context]"]

        # L1 Host
        l1 = all_data.get("L1", {}).get("data", {})
        if l1:
            lines.append(f"Host: {l1.get('hostname', '?')} | "
                         f"{l1.get('os', '?')} {l1.get('os_release', '')} | "
                         f"CPU: {l1.get('cpu', {}).get('logical_cores', '?')}c "
                         f"{l1.get('cpu', {}).get('usage_percent', '?')}% | "
                         f"RAM: {l1.get('memory', {}).get('used_gb', '?')}/"
                         f"{l1.get('memory', {}).get('total_gb', '?')}GB "
                         f"({l1.get('memory', {}).get('percent', '?')}%)")
            gpu = l1.get("gpu")
            if gpu:
                lines.append(f"GPU: {gpu[0].get('name', '?')}")

        # L2 Services
        l2 = all_data.get("L2", {}).get("data", {})
        if l2:
            ports = l2.get("ports", {}).get("listening_ports", [])
            if ports:
                key_ports = [f"{p['port']}({p.get('service_hint') or p.get('process', '?')})"
                             for p in ports[:10]]
                lines.append(f"Ports: {', '.join(key_ports)}")

            dbs = l2.get("databases", {}).get("databases", [])
            if dbs:
                db_list = [f"{d['type']}:{d.get('port', d.get('path', '?'))}" for d in dbs[:5]]
                lines.append(f"DBs: {', '.join(db_list)}")

        # L3 Network
        l3 = all_data.get("L3", {}).get("data", {})
        if l3:
            ifaces = l3.get("interfaces", {}).get("interfaces", [])
            for iface in ifaces[:3]:
                for addr in iface.get("addresses", []):
                    if addr.get("type") == "IPv4" and addr["address"] != "127.0.0.1":
                        lines.append(f"Net: {iface['name']} {addr['address']}/{addr.get('netmask', '?')}")

            arp_count = l3.get("arp", {}).get("count", 0)
            if arp_count:
                lines.append(f"ARP neighbors: {arp_count}")

        # Updated time
        latest = None
        for v in all_data.values():
            t = v.get("updated_at")
            if t and (not latest or t > latest):
                latest = t
        if latest:
            lines.append(f"Last scan: {latest}")

        return "\n".join(lines) if len(lines) > 1 else ""
    except Exception as e:
        logger.debug("[Topology] Summary error: %s", e)
        return ""


def _layer_category(layer: str) -> str:
    return {"L1": "host", "L2": "services", "L3": "network"}.get(layer, "unknown")
