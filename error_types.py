"""
错误类型定义模块
定义常见错误类型的枚举类和错误数据结构
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Any, Dict
from datetime import datetime


class ErrorLevel(Enum):
    """错误级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """错误分类"""
    # 系统错误
    SYSTEM = "system"
    DATABASE = "database"
    NETWORK = "network"
    AUTH = "auth"
    PERMISSION = "permission"
    
    # 业务错误
    VALIDATION = "validation"
    BUSINESS = "business"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    
    # 外部错误
    EXTERNAL = "external"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"


class ErrorCode(Enum):
    """错误码定义"""
    # 通用错误 (1000-1999)
    UNKNOWN = (1000, "未知错误")
    NOT_IMPLEMENTED = (1001, "功能未实现")
    INVALID_PARAMETER = (1002, "参数无效")
    MISSING_PARAMETER = (1003, "缺少必要参数")
    
    # 数据库错误 (2000-2999)
    DB_CONNECTION_FAILED = (2000, "数据库连接失败")
    DB_QUERY_FAILED = (2001, "数据库查询失败")
    DB_INSERT_FAILED = (2002, "数据插入失败")
    DB_UPDATE_FAILED = (2003, "数据更新失败")
    DB_DELETE_FAILED = (2004, "数据删除失败")
    
    # 网络错误 (3000-3999)
    NETWORK_TIMEOUT = (3000, "网络超时")
    NETWORK_UNREACHABLE = (3001, "网络不可达")
    HTTP_ERROR = (3002, "HTTP 请求错误")
    
    # 认证授权错误 (4000-4999)
    AUTH_FAILED = (4000, "认证失败")
    AUTH_EXPIRED = (4001, "认证已过期")
    PERMISSION_DENIED = (4002, "权限不足")
    TOKEN_INVALID = (4003, "Token 无效")
    
    # 业务错误 (5000-5999)
    RESOURCE_NOT_FOUND = (5000, "资源不存在")
    RESOURCE_CONFLICT = (5001, "资源冲突")
    BUSINESS_RULE_VIOLATION = (5002, "业务规则违反")
    
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message


@dataclass
class ErrorDetail:
    """错误详情"""
    field: Optional[str] = None
    value: Any = None
    message: str = ""


@dataclass
class ArcMindError(Exception):
    """ArcMind 统一错误类"""
    code: int
    message: str
    category: ErrorCategory = ErrorCategory.SYSTEM
    level: ErrorLevel = ErrorLevel.ERROR
    details: list[ErrorDetail] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    cause: Optional[Exception] = None
    
    def __post_init__(self):
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "code": self.code,
            "message": self.message,
            "category": self.category.value,
            "level": self.level.value,
            "details": [{"field": d.field, "value": d.value, "message": d.message} for d in self.details],
            "context": self.context,
            "timestamp": self.timestamp.isoformat()
        }


# ============ 便捷错误创建函数 ============

def create_error(
    code: ErrorCode,
    message: str = None,
    category: ErrorCategory = ErrorCategory.SYSTEM,
    level: ErrorLevel = ErrorLevel.ERROR,
    **kwargs
) -> ArcMindError:
    """创建错误实例的便捷函数"""
    return ArcMindError(
        code=code.code,
        message=message or code.message,
        category=category,
        level=level,
        **kwargs
    )


# ============ 预定义错误类 ============

class ValidationError(ArcMindError):
    """验证错误"""
    def __init__(self, message: str = "验证失败", **kwargs):
        super().__init__(
            code=1002,
            message=message,
            category=ErrorCategory.VALIDATION,
            level=ErrorLevel.WARNING,
            **kwargs
        )


class DatabaseError(ArcMindError):
    """数据库错误"""
    def __init__(self, message: str = "数据库错误", **kwargs):
        super().__init__(
            code=2000,
            message=message,
            category=ErrorCategory.DATABASE,
            level=ErrorLevel.ERROR,
            **kwargs
        )


class NetworkError(ArcMindError):
    """网络错误"""
    def __init__(self, message: str = "网络错误", **kwargs):
        super().__init__(
            code=3000,
            message=message,
            category=ErrorCategory.NETWORK,
            level=ErrorLevel.ERROR,
            **kwargs
        )


class AuthError(ArcMindError):
    """认证错误"""
    def __init__(self, message: str = "认证失败", **kwargs):
        super().__init__(
            code=4000,
            message=message,
            category=ErrorCategory.AUTH,
            level=ErrorLevel.ERROR,
            **kwargs
        )


class PermissionError(ArcMindError):
    """权限错误"""
    def __init__(self, message: str = "权限不足", **kwargs):
        super().__init__(
            code=4002,
            message=message,
            category=ErrorCategory.PERMISSION,
            level=ErrorLevel.ERROR,
            **kwargs
        )


class NotFoundError(ArcMindError):
    """资源不存在错误"""
    def __init__(self, message: str = "资源不存在", **kwargs):
        super().__init__(
            code=5000,
            message=message,
            category=ErrorCategory.NOT_FOUND,
            level=ErrorLevel.WARNING,
            **kwargs
        )
