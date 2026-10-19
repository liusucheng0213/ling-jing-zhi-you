"""
定位模块Pydantic模型定义
"""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class LocationReportRequest(BaseModel):
    """位置上报请求"""
    latitude: float = Field(..., ge=-90, le=90, description="纬度")
    longitude: float = Field(..., ge=-180, le=180, description="经度")
    accuracy: Optional[float] = Field(None, description="定位精度米")
    altitude: Optional[float] = Field(None, description="海拔")
    spot_id: Optional[str] = Field(None, description="识别到的景点ID")


class LocationResolveRequest(BaseModel):
    """GPS、二维码和手动选择定位请求。"""

    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    accuracy: Optional[float] = Field(None, ge=0, description="浏览器报告的 GPS 精度（米）")
    qr_value: Optional[str] = Field(None, max_length=500, description="景点编号或二维码内容")
    manual_spot_id: Optional[str] = Field(None, max_length=50)

    @model_validator(mode="after")
    def validate_gps_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude 和 longitude 必须同时提供")
        return self


class LocationAttempt(BaseModel):
    """一次定位层级的尝试记录。"""

    source: Literal["gps", "qr", "manual"]
    status: Literal["matched", "unknown", "unavailable", "invalid"]
    message: str


class LocationResolveResponse(BaseModel):
    """GPS、二维码和手动选择定位响应。"""

    source: Literal["gps", "qr", "manual", "unknown"]
    tier: int = Field(..., ge=0, le=4)
    status: Literal["matched", "unknown"]
    spot_id: Optional[str] = None
    spot_name: Optional[str] = None
    confidence: float = Field(..., ge=0, le=1)
    accuracy_meters: Optional[float] = None
    distance_meters: Optional[float] = None
    method: str
    coordinates_available: bool
    coordinate_status: Optional[Literal["verified", "estimated"]] = None
    coordinate_system: Optional[str] = None
    coordinate_source: Optional[str] = None
    coordinate_accuracy_meters: Optional[float] = None
    coordinate_verified_at: Optional[datetime] = None
    message: str
    attempts: List[LocationAttempt] = Field(default_factory=list)


class LocationSpotOption(BaseModel):
    """供二维码校验和手动定位使用的景点选项。"""

    id: str
    name: str
    scenic_area: str
    has_coordinates: bool = False
    coordinate_status: Optional[Literal["verified", "estimated"]] = None
    coordinate_system: Optional[str] = None
    coordinate_accuracy_meters: Optional[float] = None
