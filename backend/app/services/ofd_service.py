"""OFD 文件转换服务

OFD（GB/T 33118-2016）是中国版 PDF，电子发票常见格式。
本服务通过 subprocess 调用 ofdrw jar 把 OFD 转为 PNG，
后续 OCR / LLM Vision / pHash 全部复用现有图片路径。

依赖：
  - JRE（Dockerfile 已装 default-jre-headless）
  - ofdrw-tool jar（Dockerfile COPY 到 /app/lib/）

环境变量：
  - OFDRW_JAR_PATH：jar 路径，默认 /app/lib/ofdrw-tool.jar
  - OFDRW_MAX_PAGES：最多转换页数，默认 0=全部
"""

import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

OFDRW_JAR_PATH = os.getenv("OFDRW_JAR_PATH", "/app/lib/ofdrw-tool.jar")
OFDRW_MAX_PAGES = int(os.getenv("OFDRW_MAX_PAGES", "0"))
JAVA_BIN = os.getenv("JAVA_BIN", "java")

# subprocess 超时（秒），OFD 通常 1-3 页，5s 够用
SUBPROCESS_TIMEOUT = 30


class OfdConverter:
    """OFD → PNG 转换器"""

    def __init__(self):
        self.jar_path = OFDRW_JAR_PATH
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """是否配置了 jar 且能找到 java"""
        if self._available is None:
            java_ok = shutil.which(JAVA_BIN) is not None
            jar_ok = bool(self.jar_path) and os.path.exists(self.jar_path)
            self._available = java_ok and jar_ok
            if not self._available:
                logger.warning(
                    f"OFD 转换器不可用: java={java_ok}, jar={jar_ok} ({self.jar_path})"
                )
        return self._available

    def convert_to_png(self, file_data: bytes) -> Optional[bytes]:
        """OFD bytes → 首页 PNG bytes

        Returns:
            PNG bytes 成功；None 失败或不可用
        """
        if not file_data or not self.is_available():
            return None

        # 临时目录隔离，避免并发污染
        work_dir = tempfile.mkdtemp(prefix="ofd_")
        try:
            ofd_path = os.path.join(work_dir, f"{uuid.uuid4().hex}.ofd")
            with open(ofd_path, "wb") as f:
                f.write(file_data)

            # ofdrw-tool CLI: java -jar ofdrw-tool.jar convert -i input.ofd -o output_dir -t png
            # 实际子命令以所选 ofdrw 版本为准，此处占位主流用法
            cmd = [
                JAVA_BIN,
                "-Djava.awt.headless=true",
                "-jar", self.jar_path,
                "convert",
                "-i", ofd_path,
                "-o", work_dir,
                "-t", "png",
            ]
            if OFDRW_MAX_PAGES > 0:
                cmd.extend(["--max-pages", str(OFDRW_MAX_PAGES)])

            try:
                subprocess.run(
                    cmd,
                    timeout=SUBPROCESS_TIMEOUT,
                    capture_output=True,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                logger.error(f"OFD 转换超时 ({SUBPROCESS_TIMEOUT}s)")
                return None
            except Exception as e:
                logger.error(f"OFD 转换 subprocess 异常: {e}")
                return None

            # ofdrw 通常输出 Page_0.png / Page_1.png ...
            png_files = sorted(
                f for f in os.listdir(work_dir) if f.lower().endswith(".png")
            )
            if not png_files:
                logger.warning("OFD 转换未输出 PNG 文件")
                return None

            # 取首页（与 LLM 路径一致：first_page=1, last_page=1）
            with open(os.path.join(work_dir, png_files[0]), "rb") as f:
                return f.read()

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


# ===== 单例 =====
_ofd_converter: Optional[OfdConverter] = None


def get_ofd_converter() -> OfdConverter:
    global _ofd_converter
    if _ofd_converter is None:
        _ofd_converter = OfdConverter()
    return _ofd_converter
