"""游客定位服务（GPS、二维码、手动选择）。"""

import math
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


GPS_MIN_MATCH_RADIUS_METERS = 80.0
GPS_MAX_MATCH_RADIUS_METERS = 300.0

SPOT_ID_PATTERN = re.compile(r"(?<![A-Z0-9])LS-\d{3}(?!\d)", re.IGNORECASE)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """计算两个 WGS84 坐标间的球面距离（米）。"""

    earth_radius = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return earth_radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def parse_qr_spot_id(value: str) -> Optional[str]:
    """从景点编号、URL 或自定义 scheme 中提取景点 ID。"""

    match = SPOT_ID_PATTERN.search(value.strip())
    return match.group(0).upper() if match else None


class LocationService:
    """按 GPS、二维码、手动选择的层级解析当前位置。"""

    async def locate(
        self,
        spots: Iterable[Any],
        gps: Optional[Tuple[float, float]] = None,
        gps_accuracy: Optional[float] = None,
        qr_value: Optional[str] = None,
        manual_spot_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        active_spots = {str(spot.id).upper(): spot for spot in spots if spot.is_active}
        attempts: List[Dict[str, Any]] = []
        coordinate_spots = [
            spot
            for spot in active_spots.values()
            if spot.latitude is not None and spot.longitude is not None
        ]

        if gps is not None:
            if not coordinate_spots:
                attempts.append(
                    {
                        "source": "gps",
                        "status": "unavailable",
                        "message": "景点坐标库暂无可用坐标，无法将 GPS 位置可靠匹配到景点",
                    }
                )
            else:
                latitude, longitude = gps
                nearest = min(
                    coordinate_spots,
                    key=lambda spot: haversine_distance(
                        latitude,
                        longitude,
                        float(spot.latitude),
                        float(spot.longitude),
                    ),
                )
                distance = haversine_distance(
                    latitude,
                    longitude,
                    float(nearest.latitude),
                    float(nearest.longitude),
                )
                accuracy = max(float(gps_accuracy or 0), 0)
                coordinate_accuracy = max(
                    float(getattr(nearest, "coordinate_accuracy_meters", 0) or 0),
                    0,
                )
                match_radius = min(
                    GPS_MAX_MATCH_RADIUS_METERS,
                    max(GPS_MIN_MATCH_RADIUS_METERS, accuracy * 2, coordinate_accuracy),
                )
                if distance <= match_radius:
                    is_estimated = getattr(nearest, "coordinate_status", "estimated") != "verified"
                    confidence = max(
                        0.5,
                        min(
                            0.95,
                            0.95
                            - distance / match_radius * 0.25
                            - accuracy / 1000 * 0.15
                            - (0.12 if is_estimated else 0),
                        ),
                    )
                    coordinate_note = "（演示地图估算）" if is_estimated else "（地图精确点）"
                    return self._matched_response(
                        source="gps",
                        tier=1,
                        spot=nearest,
                        confidence=confidence,
                        message=f"GPS 已匹配到最近景点：{nearest.name}{coordinate_note}",
                        attempts=attempts,
                        accuracy_meters=gps_accuracy,
                        distance_meters=distance,
                        coordinates_available=True,
                    )
                attempts.append(
                    {
                        "source": "gps",
                        "status": "unknown",
                        "message": f"未进入景区可靠定位范围；最近景点距离约 {round(distance)} 米",
                    }
                )

        if qr_value:
            spot_id = parse_qr_spot_id(qr_value)
            spot = active_spots.get(spot_id) if spot_id else None
            if spot is not None:
                return self._matched_response(
                    source="qr",
                    tier=2,
                    spot=spot,
                    confidence=1.0,
                    message=f"景点二维码已识别：{spot.name}",
                    attempts=attempts,
                    method="validated_spot_qr",
                    coordinates_available=bool(coordinate_spots),
                )
            attempts.append(
                {
                    "source": "qr",
                    "status": "invalid",
                    "message": "二维码中未找到有效的景点编号",
                }
            )

        if manual_spot_id:
            spot = active_spots.get(manual_spot_id.strip().upper())
            if spot is not None:
                return self._matched_response(
                    source="manual",
                    tier=3,
                    spot=spot,
                    confidence=1.0,
                    message=f"已手动选择：{spot.name}",
                    attempts=attempts,
                    method="validated_manual_selection",
                    coordinates_available=bool(coordinate_spots),
                )
            attempts.append(
                {
                    "source": "manual",
                    "status": "invalid",
                    "message": "手动选择的景点不存在或已停用",
                }
            )

        last_attempt = attempts[-1] if attempts else None
        source = last_attempt["source"] if last_attempt else "unknown"
        method_map = {
            "gps": "nearest_spot",
            "qr": "validated_spot_qr",
            "manual": "validated_manual_selection",
        }
        return {
            "source": source,
            "tier": 0,
            "status": "unknown",
            "spot_id": None,
            "spot_name": None,
            "confidence": 0.0,
            "accuracy_meters": gps_accuracy,
            "distance_meters": None,
            "method": method_map.get(source, "none"),
            "coordinates_available": bool(coordinate_spots),
            "coordinate_status": None,
            "coordinate_system": None,
            "coordinate_source": None,
            "coordinate_accuracy_meters": None,
            "coordinate_verified_at": None,
            "message": attempts[-1]["message"] if attempts else "请选择一种定位方式",
            "attempts": attempts,
        }

    @staticmethod
    def _matched_response(
        *,
        source: str,
        tier: int,
        spot: Any,
        confidence: float,
        message: str,
        attempts: List[Dict[str, Any]],
        accuracy_meters: Optional[float] = None,
        distance_meters: Optional[float] = None,
        method: str = "nearest_spot",
        coordinates_available: bool = False,
    ) -> Dict[str, Any]:
        return {
            "source": source,
            "tier": tier,
            "status": "matched",
            "spot_id": spot.id,
            "spot_name": spot.name,
            "confidence": round(confidence, 2),
            "accuracy_meters": round(accuracy_meters, 1) if accuracy_meters is not None else None,
            "distance_meters": round(distance_meters, 1) if distance_meters is not None else None,
            "method": method,
            "coordinates_available": coordinates_available,
            "coordinate_status": getattr(spot, "coordinate_status", None),
            "coordinate_system": getattr(spot, "coordinate_system", None),
            "coordinate_source": getattr(spot, "coordinate_source", None),
            "coordinate_accuracy_meters": getattr(spot, "coordinate_accuracy_meters", None),
            "coordinate_verified_at": getattr(spot, "coordinate_verified_at", None),
            "message": message,
            "attempts": attempts,
        }
