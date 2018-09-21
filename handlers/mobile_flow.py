from routes.middleware import path_params
from sanic.views import HTTPMethodView
from .legal_url import legal_mobile_flow, legal_gas_card_account_info
from . import base_fn
from services import http_request
import ujson
from conf import conf
from sanic.response import json


class MobileFlowView(HTTPMethodView):
    @path_params
    @legal_mobile_flow
    async def get(self, req):
        params = req['context'].path_params
        mobile_no = params['mobile_no']
        flow = params['flow']

        params = {
            "method": conf.MOBILE_GETITEM_INFO,
            "mobileNo": params['mobile_no'],
            "rechargeAmount": 100
        }
        urls = base_fn.gen_urls(params)
        res = await http_request.get_flow(req, urls)
        res = ujson.loads(res)

        print(res)


class MobileFlowView(HTTPMethodView):
    @path_params
    @legal_mobile_flow
    async def get(self, req):
        params = req['context'].path_params
        mobile_no = params['mobile_no']
        flow = params['flow']

        params = {
            "method": conf.MOBILE_GETITEM_INFO,
            "mobileNo": params['mobile_no'],
            "rechargeAmount": 100
        }
        urls = base_fn.gen_urls(params)
        res = await http_request.get_flow(req, urls)
        res = ujson.loads(res)

        print(res)


class GasCardAccountInfo(HTTPMethodView):
    @path_params
    @legal_gas_card_account_info
    async def post(self, req):
        body = req.json
        # params = {
        #     'province': body['province'],
        #     'operator': body['operator'],
        #     'gasCardNo': body['card_no'],
        #     "method": conf.GAS_CARD_ACCOUNT_INFO
        # }
        params = {
            "method": conf.GAS_CARD_ITEM_LIST
        }
        urls = base_fn.gen_urls(params)
        print(f'{conf.BM_SERVER}?{urls}')
        res = await http_request.get_gas_account_info(req, urls)
        res = ujson.loads(res)
        return json(res)
