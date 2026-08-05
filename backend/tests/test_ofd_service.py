"""ofd_service 单元测试

OfdConverter 在无 JRE / 无 jar 环境下应优雅降级返回 None，
不抛异常阻断主流程。subprocess 失败时也应被吞掉。
"""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.ofd_service import OfdConverter, get_ofd_converter


class TestOfdConverterAvailability:
    def test_unavailable_when_no_java_no_jar(self):
        """无 java 且无 jar → is_available() False"""
        with patch("app.services.ofd_service.shutil.which", return_value=None), \
             patch("os.path.exists", return_value=False):
            conv = OfdConverter()
            conv._available = None  # 重置缓存
            assert conv.is_available() is False

    def test_unavailable_when_java_but_no_jar(self):
        """有 java 无 jar → False"""
        with patch("app.services.ofd_service.shutil.which", return_value="/usr/bin/java"), \
             patch("os.path.exists", return_value=False):
            conv = OfdConverter()
            conv._available = None
            assert conv.is_available() is False

    def test_available_when_both_present(self):
        """有 java 且有 jar → True"""
        with patch("app.services.ofd_service.shutil.which", return_value="/usr/bin/java"), \
             patch("os.path.exists", return_value=True):
            conv = OfdConverter()
            conv._available = None
            assert conv.is_available() is True


class TestConvertToPngDegraded:
    """降级场景：不可用时返回 None，不抛异常"""

    def test_unavailable_returns_none(self):
        with patch("app.services.ofd_service.shutil.which", return_value=None), \
             patch("os.path.exists", return_value=False):
            conv = OfdConverter()
            conv._available = None
            assert conv.convert_to_png(b"fake ofd bytes") is None

    def test_empty_input_returns_none(self):
        """空 bytes → None（不调用 subprocess）"""
        conv = OfdConverter()
        conv._available = True  # 强制可用
        assert conv.convert_to_png(b"") is None

    def test_subprocess_timeout_returns_none(self):
        """subprocess 超时 → None，不抛异常"""
        from subprocess import TimeoutExpired
        with patch("app.services.ofd_service.shutil.which", return_value="/usr/bin/java"), \
             patch("os.path.exists", return_value=True), \
             patch("subprocess.run", side_effect=TimeoutExpired(cmd="java", timeout=30)):
            conv = OfdConverter()
            conv._available = None
            result = conv.convert_to_png(b"fake ofd bytes")
            assert result is None

    def test_subprocess_exception_returns_none(self):
        """subprocess 抛异常 → None"""
        with patch("app.services.ofd_service.shutil.which", return_value="/usr/bin/java"), \
             patch("os.path.exists", return_value=True), \
             patch("subprocess.run", side_effect=RuntimeError("boom")):
            conv = OfdConverter()
            conv._available = None
            result = conv.convert_to_png(b"fake ofd bytes")
            assert result is None

    def test_no_png_output_returns_none(self):
        """subprocess 跑通但未输出 PNG → None"""
        mock_run = MagicMock(returncode=0)
        with patch("app.services.ofd_service.shutil.which", return_value="/usr/bin/java"), \
             patch("os.path.exists", return_value=True), \
             patch("subprocess.run", return_value=mock_run), \
             patch("os.listdir", return_value=[]):
            conv = OfdConverter()
            conv._available = None
            result = conv.convert_to_png(b"fake ofd bytes")
            assert result is None


class TestConvertToPngHappy:
    def test_returns_png_bytes_on_success(self):
        """成功 → 返回 PNG bytes"""
        mock_run = MagicMock(returncode=0)
        fake_png = b"\x89PNG\r\n\x1a\n" + b"x" * 100
        with patch("app.services.ofd_service.shutil.which", return_value="/usr/bin/java"), \
             patch("os.path.exists", return_value=True), \
             patch("subprocess.run", return_value=mock_run), \
             patch("os.listdir", return_value=["Page_0.png", "Page_1.png"]), \
             patch("builtins.open", new_callable=MagicMock) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = fake_png
            conv = OfdConverter()
            conv._available = None
            result = conv.convert_to_png(b"fake ofd bytes")
            assert result == fake_png

    def test_picks_first_page(self):
        """多页时取首页（按文件名排序后第一个）"""
        mock_run = MagicMock(returncode=0)
        fake_png = b"\x89PNG" + b"\x00" * 50
        with patch("app.services.ofd_service.shutil.which", return_value="/usr/bin/java"), \
             patch("os.path.exists", return_value=True), \
             patch("subprocess.run", return_value=mock_run), \
             patch("os.listdir", return_value=["Page_2.png", "Page_0.png", "Page_1.png"]), \
             patch("builtins.open", new_callable=MagicMock) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = fake_png
            conv = OfdConverter()
            conv._available = None
            result = conv.convert_to_png(b"fake ofd bytes")
            assert result == fake_png
            # 应该读 Page_0.png（排序后第一个）
            opened_path = mock_open.call_args[0][0]
            assert "Page_0.png" in opened_path


class TestSingleton:
    def test_get_ofd_converter_returns_same_instance(self):
        a = get_ofd_converter()
        b = get_ofd_converter()
        assert a is b
