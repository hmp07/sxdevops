"""带生命周期的 Token 认证：超过最大有效期（天）自动失效。"""
import os
from datetime import timedelta

from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication


def token_max_age_days():
    value = os.environ.get('SXDEVOPS_TOKEN_MAX_AGE_DAYS', '30').strip()
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 30


class ExpiringTokenAuthentication(TokenAuthentication):
    """TokenAuthentication 子类：token.created 超过 SXDEVOPS_TOKEN_MAX_AGE_DAYS 即失效。

    失效时删除 token 记录（强制重新登录）；0 表示永不过期。
    """

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        max_age = token_max_age_days()
        if max_age > 0 and token.created:
            age = timezone.now() - token.created
            if age > timedelta(days=max_age):
                token.delete()
                raise exceptions.AuthenticationFailed('Token 已过期，请重新登录。')
        return user, token


def rotate_token_if_expired(token):
    """登录时检查：token 超龄则删除重建（返回最终 token）。"""
    from rest_framework.authtoken.models import Token as AuthToken

    max_age = token_max_age_days()
    if max_age > 0 and token.created and (timezone.now() - token.created) > timedelta(days=max_age):
        user = token.user
        token.delete()
        token, _ = AuthToken.objects.get_or_create(user=user)
    return token
