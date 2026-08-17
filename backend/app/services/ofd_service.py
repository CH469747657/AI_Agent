"""OFD 文件转换服务

OFD（GB/T 33118-2016）是中国版 PDF，电子发票常见格式。
本服务通过 subprocess 调用 ofd2img.jar（含 ofdrw-converter + 所有依赖）把 OFD 转为 PDF，
然后用 poppler 的 pdftoppm 把 PDF 转为 PNG。

依赖：
  - JRE（Dockerfile 已装 default-jre-headless）
  - ofd2img.jar（fat jar，含 ofdrw-converter 2.3.7 + 所有依赖，构建到 /app/lib/）
  - poppler-utils（pdftoppm，Dockerfile 已装）

环境变量：
  - OFD2IMG_JAR_PATH：jar 路径，默认 /app/lib/ofd2img.jar
  - OFD2IMG_DPI：PDF→PNG 渲染分辨率，默认 150
"""

import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

OFD2IMG_JAR_PATH = os.getenv("OFD2IMG_JAR_PATH", "/app/lib/ofd2img.jar")
OFD2IMG_DPI = int(os.getenv("OFD2IMG_DPI", "150"))
JAVA_BIN = os.getenv("JAVA_BIN", "java")

# subprocess 超时（秒），OFD 通常 1-3 页，30s 够用
SUBPROCESS_TIMEOUT = 60


class OfdConverter:
    """OFD → PNG 转换器"""

    def __init__(self):
        self.jar_path = OFD2IMG_JAR_PATH
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """是否配置了 jar + java + pdftoppm"""
        if self._available is None:
            java_ok = shutil.which(JAVA_BIN) is not None
            jar_ok = bool(self.jar_path) and os.path.exists(self.jar_path)
            pdftoppm_ok = shutil.which("pdftoppm") is not None
            self._available = java_ok and jar_ok and pdftoppm_ok
            if not self._available:
                logger.warning(
                    f"OFD 转换器不可用: java={java_ok}, jar={jar_ok} ({self.jar_path}), pdftoppm={pdftoppm_ok}"
                )
        return self._available

    def convert_to_png(self, file_data: bytes) -> Optional[bytes]:
        """OFD bytes → 首页 PNG bytes

        流程：OFD → ofd2img.jar → PDF → pdftoppm → PNG

        Returns: PNG bytes 成功；None 失败或不可用
        """
        if not file_data or not self.is_available():
            return None

        work_dir = tempfile.mkdtemp(prefix="ofd_")
        try:
            # 1. 写 OFD 输入文件
            ofd_path = os.path.join(work_dir, f"{uuid.uuid4().hex}.ofd")
            with open(ofd_path, "wb") as f:
                f.write(file_data)

            # 2. ofd2img.jar 把 OFD → PDF
            pdf_path = os.path.join(work_dir, "output.pdf")
            cmd = [
                JAVA_BIN,
                "-Djava.awt.headless=true",
                "-jar", self.jar_path,
                ofd_path,
                pdf_path,
            ]
            try:
                result = subprocess.run(
                    cmd,
                    timeout=SUBPROCESS_TIMEOUT,
                    capture_output=True,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                logger.error(f"OFD→PDF 转换超时 ({SUBPROCESS_TIMEOUT}s)")
                return None
            except Exception as e:
                logger.error(f"OFD→PDF subprocess 异常: {e}")
                return None

            if not os.path.exists(pdf_path):
                logger.warning(
                    f"OFD→PDF 失败: stderr={result.stderr.decode(errors='replace')[:200]}"
                )
                return None

            # 3. pdftoppm 把 PDF → PNG
            png_prefix = os.path.join(work_dir, "page")
            try:
                subprocess.run(
                    ["pdftoppm", "-png", "-r", str(OFD2IMG_DPI),
                     "-f", "1", "-l", "1",
                     pdf_path, png_prefix],
                    timeout=SUBPROCESS_TIMEOUT,
                    capture_output=True,
                    check=False,
                )
            except Exception as e:
                logger.error(f"PDF→PNG 异常: {e}")
                return None

            # pdftoppm 输出 prefix-1.png
            actual_png = f"{png_prefix}-1.png"
            if not os.path.exists(actual_png):
                # 兜底查找 prefix-*.png
                import glob
                candidates = sorted(glob.glob(f"{png_prefix}*.png"))
                if not candidates:
                    logger.warning("PDF→PNG 未输出 PNG 文件")
                    return None
                actual_png = candidates[0]

            with open(actual_png, "rb") as f:
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
