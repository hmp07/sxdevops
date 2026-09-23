"""项目级安全配置守卫测试（SECRET_KEY 校验函数）。"""

from django.test import SimpleTestCase

from sxdevops.settings import _SECRET_KEY_FALLBACK, _validate_secret_key


class SecretKeyGuardTests(SimpleTestCase):
    def test_production_rejects_repo_default_secret_key(self):
        """生产模式使用仓库默认密钥（操作员误配置）必须拒绝启动。"""
        with self.assertRaises(RuntimeError):
            _validate_secret_key(_SECRET_KEY_FALLBACK, debug=False, is_test_run=False)

    def test_production_accepts_custom_secret_key(self):
        self.assertEqual(
            _validate_secret_key('deployed-random-key', debug=False, is_test_run=False),
            'deployed-random-key',
        )

    def test_dev_and_test_runs_fall_back_to_default(self):
        self.assertEqual(_validate_secret_key('', debug=True, is_test_run=False), _SECRET_KEY_FALLBACK)
        self.assertEqual(_validate_secret_key('', debug=False, is_test_run=True), _SECRET_KEY_FALLBACK)

    def test_production_missing_secret_key_raises(self):
        with self.assertRaises(RuntimeError):
            _validate_secret_key('', debug=False, is_test_run=False)
