"""定位相关 API，提供 GPS、二维码和手动定位。"""

from typing import List, Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.location_service import LocationService
from app.database import get_db
from app.models import BehaviorLog, Spot
from app.schemas.location import (
    LocationReportRequest,
    LocationResolveRequest,
    LocationResolveResponse,
    LocationSpotOption,
)
from app.utils.jwt import get_current_user

router = APIRouter(tags=["定位"])
location_service = LocationService()


async def _get_active_spots(db: AsyncSession) -> list[Spot]:
    result = await db.execute(
        select(Spot)
        .where(Spot.is_active.is_(True))
        .order_by(Spot.route_order.asc(), Spot.id.asc())
    )
    return list(result.scalars().all())


@router.post("/location", status_code=status.HTTP_204_NO_CONTENT, summary="上报当前位置")
async def report_location(
    request: LocationReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """记录游客主动上报的位置，用于定位质量分析。"""

    log = BehaviorLog(
        user_id=current_user.get("user_id") if current_user else None,
        event_type="location_report",
        event_data={
            "latitude": request.latitude,
            "longitude": request.longitude,
            "accuracy": request.accuracy,
            "altitude": request.altitude,
        },
        spot_id=request.spot_id,
    )
    db.add(log)
    await db.commit()
    return None


@router.get(
    "/location/spots",
    response_model=List[LocationSpotOption],
    summary="获取可定位景点",
)
async def get_location_spots(db: AsyncSession = Depends(get_db)):
    """返回活跃景点，供二维码校验和手动定位选择。"""

    spots = await _get_active_spots(db)
    return [
        LocationSpotOption(
            id=spot.id,
            name=spot.name,
            scenic_area=spot.scenic_area,
            has_coordinates=spot.latitude is not None and spot.longitude is not None,
            coordinate_status=spot.coordinate_status,
            coordinate_system=spot.coordinate_system,
            coordinate_accuracy_meters=spot.coordinate_accuracy_meters,
        )
        for spot in spots
    ]


@router.post(
    "/location/resolve",
    response_model=LocationResolveResponse,
    summary="按 GPS、二维码和手动链路解析位置",
)
async def resolve_location(
    request: LocationResolveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """按 GPS、二维码、手动选择的顺序解析景点。"""

    spots = await _get_active_spots(db)
    gps = None
    if request.latitude is not None and request.longitude is not None:
        gps = (request.latitude, request.longitude)

    result = await location_service.locate(
        spots,
        gps=gps,
        gps_accuracy=request.accuracy,
        qr_value=request.qr_value,
        manual_spot_id=request.manual_spot_id,
    )

    db.add(
        BehaviorLog(
            user_id=current_user.get("user_id") if current_user else None,
            event_type="location_resolve",
            event_data={
                "source": result["source"],
                "status": result["status"],
                "confidence": result["confidence"],
                "accuracy_meters": result["accuracy_meters"],
                "distance_meters": result["distance_meters"],
                "method": result["method"],
                "coordinate_status": result["coordinate_status"],
                "coordinate_system": result["coordinate_system"],
                "attempts": result["attempts"],
            },
            spot_id=result["spot_id"],
        )
    )
    await db.commit()
    return LocationResolveResponse(**result)
