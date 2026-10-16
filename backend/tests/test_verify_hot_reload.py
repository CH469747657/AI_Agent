"""VerifyService 配置热更新测试 — 页面保存验真凭据后无需重启即生效

背景（2026-10-16 排查）：VerifyService 单例在 __init__ 把 provider/api_key/
secret_key/appcode 快照到实例属性，页面 PUT /api/settings/verify 后单例
仍用旧值，需重启后端才生效。修复：属性改为 @property 实时读 settings，
与 verify_enabled（本就实时读）行为对齐。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.config import settings
from app.services.verify_service import VerifyService, get_verify_service, reset_verify_service


@pytest.fixture(autouse=True)
def save_and_restore_settings():
    saved = (
        settings.verify_provider,
        settings.verify_api_key,
        settings.verify_secret_key,
        settings.aliyun_verify_appcode,
        settings.aliyun_verify_appsecret,
        settings.verify_enabled,
    )
    yield
    (
        settings.verify_provider,
        settings.verify_api_key,
        settings.verify_secret_key,
        settings.aliyun_verify_appcode,
        settings.aliyun_verify_appsecret,
        settings.verify_enabled,
    ) = saved
    reset_verify_service()


class TestLiveConfigRead:
    """凭据属性实时读 settings，页面保存后单例立即感知"""

    def test_provider_reads_live(self):
        svc = VerifyService()
        settings.verify_provider = "baidu"
        assert svc.provider == "baidu"
        settings.verify_provider = "aliyun"
        assert svc.provider == "aliyun"

    def test_api_key_reads_live(self):
        svc = VerifyService()
        settings.verify_api_key = "new-ak"
        assert svc.api_key == "new-ak"

    def test_aliyun_appcode_reads_live(self):
        svc = VerifyService()
        settings.aliyun_verify_appcode = "new-appcode"
        assert svc.aliyun_appcode == "new-appcode"

    def test_secret_key_reads_live(self):
        svc = VerifyService()
        settings.verify_secret_key = "new-sk"
        assert svc.secret_key == "new-sk"

    def test_aliyun_appsecret_reads_live(self):
        svc = VerifyService()
        settings.aliyun_verify_appsecret = "new-appsecret"
        assert svc.aliyun_appsecret == "new-appsecret"


class TestEnabledFlagsLive:
    """可用性判断随配置实时变化"""

    def test_aliyun_enabled_flips_with_appcode(self):
        settings.aliyun_verify_appcode = ""
        svc = VerifyService()
        assert svc.aliyun_enabled is False
        settings.aliyun_verify_appcode = "code-1"
        assert svc.aliyun_enabled is True

    def test_baidu_enabled_flips_with_credentials(self):
        settings.verify_api_key = ""
        settings.verify_secret_key = ""
        svc = VerifyService()
        assert svc.baidu_enabled is False
        settings.verify_api_key = "ak"
        settings.verify_secret_key = "sk"
        assert svc.baidu_enabled is True

    def test_provider_enabled_flips_with_provider(self):
        settings.verify_api_key = "ak"
        settings.verify_secret_key = "sk"
        settings.aliyun_verify_appcode = ""
        settings.verify_provider = "baidu"
        svc = VerifyService()
        assert svc.provider_enabled is True
        settings.verify_provider = "aliyun"
        assert svc.provider_enabled is False

    def test_enabled_property_combines_switch_and_provider(self):
        """verify_enabled 开关（本就实时）× provider_enabled（修复后实时）"""
        settings.verify_provider = "aliyun"
        settings.aliyun_verify_appcode = "code-1"
        settings.verify_enabled = False
        svc = VerifyService()
        assert svc.enabled is False
        settings.verify_enabled = True
        assert svc.enabled is True


class TestSingletonReset:
    """reset_verify_service：单例重置（测试/极端场景用；热更新不再依赖它）"""

    def test_reset_creates_fresh_instance(self):
        a = get_verify_service()
        reset_verify_service()
        b = get_verify_service()
        assert b is not a
