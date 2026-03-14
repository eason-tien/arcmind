"""
错误检测模块
实现语法错误、导入错误、文件权限错误、网络错误等检测逻辑
"""

import ast
import os
import sys
import subprocess
import socket
import urllib.request
import urllib.error
import traceback
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field

from error_types import (
    ErrorCode, ErrorCategory, ErrorLevel, 
    ArcMindError, ErrorDetail
)


@dataclass
class DetectionResult:
    """检测结果"""
    detected: bool
    error_code: Optional[ErrorCode] = None
    message: str = ""
    details: List[ErrorDetail] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_error(self) -> Optional[ArcMindError]:
        """转换为 ArcMindError"""
        if not self.detected or not self.error_code:
            return None
        return ArcMindError(
            code=self.error_code.code,
            message=self.message,
            category=ErrorCategory.SYSTEM,
            level=ErrorLevel.ERROR,
            details=self.details,
            context=self.context
        )


# ============ 语法错误检测 ============

class SyntaxErrorDetector:
    """Python 语法错误检测器"""
    
    @staticmethod
    def detect_file(file_path: str) -> DetectionResult:
        """检测文件语法错误"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()
            return SyntaxErrorDetector.detect_source(source, file_path)
        except FileNotFoundError:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.RESOURCE_NOT_FOUND,
                message=f"文件不存在: {file_path}"
            )
        except PermissionError:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.PERMISSION_DENIED,
                message=f"无权限读取文件: {file_path}"
            )
        except Exception as e:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.UNKNOWN,
                message=f"读取文件失败: {str(e)}"
            )
    
    @staticmethod
    def detect_source(source: str, filename: str = "<string>") -> DetectionResult:
        """检测源代码语法错误"""
        try:
            ast.parse(source, filename=filename)
            return DetectionResult(
                detected=False,
                message="无语法错误"
            )
        except SyntaxError as e:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.INVALID_PARAMETER,
                message=f"语法错误: {e.msg}",
                details=[
                    ErrorDetail(field="line", value=e.lineno, message=f"行号 {e.lineno}"),
                    ErrorDetail(field="offset", value=e.offset, message=f"列号 {e.offset}"),
                    ErrorDetail(field="text", value=e.text, message="错误行内容")
                ],
                context={
                    "filename": filename,
                    "error_type": "SyntaxError"
                }
            )
        except Exception as e:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.UNKNOWN,
                message=f"解析失败: {str(e)}"
            )
    
    @staticmethod
    def detect_code_snippet(code: str) -> DetectionResult:
        """检测代码片段语法错误"""
        return SyntaxErrorDetector.detect_source(code, "<snippet>")


# ============ 导入错误检测 ============

class ImportErrorDetector:
    """导入错误检测器"""
    
    @staticmethod
    def detect_import(module_name: str) -> DetectionResult:
        """检测模块导入错误"""
        # 尝试实际导入
        try:
            __import__(module_name)
            return DetectionResult(
                detected=False,
                message=f"模块 {module_name} 导入成功"
            )
        except ImportError as e:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.INVALID_PARAMETER,
                message=f"导入错误: {str(e)}",
                details=[
                    ErrorDetail(field="module", value=module_name, message="模块名称"),
                    ErrorDetail(field="error", value=str(e), message="错误信息")
                ],
                context={"error_type": "ImportError"}
            )
        except Exception as e:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.UNKNOWN,
                message=f"未知导入错误: {str(e)}"
            )
    
    @staticmethod
    def detect_file_imports(file_path: str) -> List[DetectionResult]:
        """检测文件中的所有导入语句"""
        results = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()
            
            tree = ast.parse(source)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        results.append(ImportErrorDetector.detect_import(alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        results.append(ImportErrorDetector.detect_import(node.module))
                        
        except Exception as e:
            results.append(DetectionResult(
                detected=True,
                error_code=ErrorCode.UNKNOWN,
                message=f"分析失败: {str(e)}"
            ))
        
        return results


# ============ 文件权限错误检测 ============

class PermissionErrorDetector:
    """文件权限错误检测器"""
    
    PERMISSION_MAPPING = {
        "read": os.R_OK,
        "write": os.W_OK,
        "execute": os.X_OK
    }
    
    @staticmethod
    def check_file_permission(
        file_path: str, 
        check_type: str = "read"
    ) -> DetectionResult:
        """检测文件权限"""
        if not os.path.exists(file_path):
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.RESOURCE_NOT_FOUND,
                message=f"文件不存在: {file_path}"
            )
        
        mode = PermissionErrorDetector.PERMISSION_MAPPING.get(
            check_type.lower(), os.R_OK
        )
        
        has_permission = os.access(file_path, mode)
        
        if has_permission:
            return DetectionResult(
                detected=False,
                message=f"文件 {check_type} 权限正常"
            )
        
        return DetectionResult(
            detected=True,
            error_code=ErrorCode.PERMISSION_DENIED,
            message=f"文件 {check_type} 权限不足: {file_path}",
            details=[
                ErrorDetail(field="path", value=file_path, message="文件路径"),
                ErrorDetail(field="check_type", value=check_type, message="权限类型"),
                ErrorDetail(field="current_mode", value=oct(os.stat(file_path).st_mode), message="当前权限")
            ],
            context={"required_permission": check_type}
        )
    
    @staticmethod
    def check_directory_writable(dir_path: str) -> DetectionResult:
        """检测目录写权限"""
        if not os.path.exists(dir_path):
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.RESOURCE_NOT_FOUND,
                message=f"目录不存在: {dir_path}"
            )
        
        if not os.path.isdir(dir_path):
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.INVALID_PARAMETER,
                message=f"路径不是目录: {dir_path}"
            )
        
        test_file = os.path.join(dir_path, f".write_test_{os.getpid()}")
        try:
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            return DetectionResult(
                detected=False,
                message="目录可写"
            )
        except PermissionError:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.PERMISSION_DENIED,
                message=f"目录无写权限: {dir_path}"
            )
        except Exception as e:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.UNKNOWN,
                message=f"检测失败: {str(e)}"
            )
    
    @staticmethod
    def check_executable(file_path: str) -> DetectionResult:
        """检测文件可执行权限"""
        return PermissionErrorDetector.check_file_permission(file_path, "execute")


# ============ 网络错误检测 ============

class NetworkErrorDetector:
    """网络错误检测器"""
    
    @staticmethod
    def check_connectivity(
        host: str = "8.8.8.8", 
        port: int = 53, 
        timeout: int = 3
    ) -> DetectionResult:
        """检测网络连接"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            try:
                sock.connect((host, port))
            finally:
                sock.close()
            return DetectionResult(
                detected=False,
                message="网络连接正常"
            )
        except socket.timeout:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.NETWORK_TIMEOUT,
                message=f"网络超时: {host}:{port}",
                context={"host": host, "port": port, "timeout": timeout}
            )
        except socket.gaierror:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.NETWORK_UNREACHABLE,
                message=f"DNS 解析失败: {host}",
                context={"host": host}
            )
        except Exception as e:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.NETWORK_UNREACHABLE,
                message=f"网络错误: {str(e)}"
            )
    
    @staticmethod
    def check_url_accessible(
        url: str, 
        timeout: int = 10
    ) -> DetectionResult:
        """检测 URL 是否可访问"""
        try:
            response = urllib.request.urlopen(url, timeout=timeout)
            status_code = response.getcode()
            
            if 200 <= status_code < 400:
                return DetectionResult(
                    detected=False,
                    message=f"URL 可访问 (HTTP {status_code})"
                )
            
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.HTTP_ERROR,
                message=f"HTTP 错误: {status_code}",
                details=[
                    ErrorDetail(field="url", value=url, message="请求 URL"),
                    ErrorDetail(field="status_code", value=status_code, message="HTTP 状态码")
                ]
            )
            
        except urllib.error.URLError as e:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.NETWORK_TIMEOUT if "timed out" in str(e) else ErrorCode.NETWORK_UNREACHABLE,
                message=f"URL 访问失败: {str(e.reason)}",
                details=[
                    ErrorDetail(field="url", value=url, message="请求 URL")
                ]
            )
        except Exception as e:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.UNKNOWN,
                message=f"未知错误: {str(e)}"
            )
    
    @staticmethod
    def ping_host(host: str, count: int = 3) -> DetectionResult:
        """Ping 检测主机"""
        try:
            result = subprocess.run(
                ["ping", "-c", str(count), host],
                capture_output=True,
                text=True,
                timeout=count * 2 + 5
            )
            
            if result.returncode == 0:
                return DetectionResult(
                    detected=False,
                    message=f"Ping {host} 成功"
                )
            
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.NETWORK_UNREACHABLE,
                message=f"Ping {host} 失败",
                details=[
                    ErrorDetail(field="host", value=host, message="目标主机"),
                    ErrorDetail(field="output", value=result.stdout, message="ping 输出")
                ]
            )
        except subprocess.TimeoutExpired:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.NETWORK_TIMEOUT,
                message=f"Ping 超时: {host}"
            )
        except FileNotFoundError:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.UNKNOWN,
                message="ping 命令不可用"
            )
        except Exception as e:
            return DetectionResult(
                detected=True,
                error_code=ErrorCode.UNKNOWN,
                message=f"Ping 失败: {str(e)}"
            )


# ============ 异常错误检测 ============

class ExceptionDetector:
    """异常错误检测器"""
    
    COMMON_EXCEPTIONS = {
        "ZeroDivisionError": ErrorCode.INVALID_PARAMETER,
        "IndexError": ErrorCode.RESOURCE_NOT_FOUND,
        "KeyError": ErrorCode.RESOURCE_NOT_FOUND,
        "ValueError": ErrorCode.INVALID_PARAMETER,
        "TypeError": ErrorCode.INVALID_PARAMETER,
        "AttributeError": ErrorCode.INVALID_PARAMETER,
        "IOError": ErrorCode.SYSTEM,
        "OSError": ErrorCode.SYSTEM,
        "MemoryError": ErrorCode.SYSTEM,
        "RecursionError": ErrorCode.SYSTEM,
    }
    
    @staticmethod
    def detect_exception(exc: Exception) -> DetectionResult:
        """检测异常类型"""
        exc_type = type(exc).__name__
        exc_message = str(exc)
        
        error_code = ExceptionDetector.COMMON_EXCEPTIONS.get(
            exc_type, ErrorCode.UNKNOWN
        )
        
        return DetectionResult(
            detected=True,
            error_code=error_code,
            message=f"{exc_type}: {exc_message}",
            details=[
                ErrorDetail(field="exception_type", value=exc_type, message="异常类型"),
                ErrorDetail(field="message", value=exc_message, message="异常信息"),
                ErrorDetail(field="traceback", value=traceback.format_exc(), message="堆栈跟踪")
            ],
            context={
                "exception_module": exc.__class__.__module__
            }
        )
    
    @staticmethod
    def is_critical_exception(exc: Exception) -> bool:
        """判断是否为严重异常"""
        critical_types = (
            SystemExit, KeyboardInterrupt, 
            MemoryError, RecursionError
        )
        return isinstance(exc, critical_types)


# ============ 综合错误检测器 ============

class ErrorDetector:
    """综合错误检测器"""
    
    def __init__(self):
        self.syntax = SyntaxErrorDetector()
        self.import_detector = ImportErrorDetector()
        self.permission = PermissionErrorDetector()
        self.network = NetworkErrorDetector()
        self.exception = ExceptionDetector()
    
    def detect_from_exception(self, exc: Exception) -> ArcMindError:
        """从异常创建错误"""
        result = self.exception.detect_exception(exc)
        return result.to_error()
    
    def detect_file_issues(self, file_path: str) -> List[DetectionResult]:
        """检测文件相关问题"""
        results = []
        
        # 语法检测
        results.append(self.syntax.detect_file(file_path))
        
        # 权限检测
        if os.path.exists(file_path):
            results.append(self.permission.check_file_permission(file_path))
        
        return [r for r in results if r.detected]
    
    def detect_system_health(self) -> Dict[str, DetectionResult]:
        """系统健康检测"""
        return {
            "network": self.network.check_connectivity(),
            "disk_writable": self.permission.check_directory_writable("/tmp")
        }


# ============ CLI 入口 ============

def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="错误检测工具")
    parser.add_argument("--syntax", help="检测 Python 语法错误")
    parser.add_argument("--import", dest="import_check", help="检测模块导入")
    parser.add_argument("--permission", help="检测文件权限")
    parser.add_argument("--network", help="检测网络连接")
    parser.add_argument("--url", help="检测 URL 可访问性")
    parser.add_argument("--health", action="store_true", help="系统健康检测")
    
    args = parser.parse_args()
    
    detector = ErrorDetector()
    
    if args.syntax:
        result = detector.syntax.detect_file(args.syntax)
        print(f"语法检测: {result.message}")
        if result.detected:
            print(f"  错误码: {result.error_code}")
            for d in result.details:
                print(f"  {d.field}: {d.value}")
    
    if args.import_check:
        result = detector.import_detector.detect_import(args.import_check)
        print(f"导入检测: {result.message}")
    
    if args.permission:
        result = detector.permission.check_file_permission(args.permission)
        print(f"权限检测: {result.message}")
    
    if args.network:
        result = detector.network.check_connectivity(args.network)
        print(f"网络检测: {result.message}")
    
    if args.url:
        result = detector.network.check_url_accessible(args.url)
        print(f"URL 检测: {result.message}")
    
    if args.health:
        results = detector.detect_system_health()
        for key, result in results.items():
            print(f"{key}: {result.message}")


if __name__ == "__main__":
    main()
