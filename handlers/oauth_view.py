from sanic.response import text, json
from .verification import create_token, get_wxapp_userinfo
from routes.middleware import path_params, query_validators, body_validators, token_validate
from sanic.views import HTTPMethodView
from models.v1.oauth import Account
from models.v1 import generation_objectid


class OauthTokenCode(HTTPMethodView):
    @path_params
    async def post(self, req):
        is_validate, token = create_token(req)
        if not is_validate:
            return text('user not registerd', 401)
        return json({
            'access_token': token['access_token'],
            'sub': token['account_id'],
            'token_type': 'jwt'
        })


class AccountsWxapp(HTTPMethodView):
    @path_params
    async def post(self, req):
        encrypted_data = req.json.get('username')
        iv = req.json.get('password')
        code = req.json.get('code')
        user_info = get_wxapp_userinfo(encrypted_data, iv, code)
        openid = user_info.get('openId')
        account = Account.get_by_wxapp(openid=openid)
        if account:
            return text('user_registerd_already', 400)
        params = {
            'id': generation_objectid(),
            'nickname': user_info['nickName'],
            'avatar': user_info['avatarUrl'],
            'authentications': {'wxapp': openid},
        }
        account = Account(**params)
        account.save()
        return json({
            'id': account.id
        })
