from conf import enum
from sanic.response import text


def legal_mobile_flow(f):
    async def g(view, req):
        params = req['context'].path_params
        if params['mobile_no'] is None or params['flow'] is None:
            return text('', 400)
        else:
            return await f(view, req)

    return g


def legal_gas_card_account_info(f):
    async def g(view, req):
        params = req.json
        ness = ['province', 'operator', 'card_no']
        for i in ness:
            if not params.__contains__(i):
                return text(f'{i} is required', 400)
        if params['province'] not in enum.PROVINCES or params['operator'] not in enum.OPERATORS:
            return text('province or operator is null', 400)
        elif params['operator'] == 'sinopec' and len(params['card_no']) != 19:
            return text('中石化加油卡卡号错误', 400)
        elif params['operator'] == 'cnpc' and len(params['card_no']) != 16:
            return text('中石油加油卡卡号错误', 400)
        else:
            return await f(view, req)

    return g


def legal_url_browse_item(f):
    async def g(view, req):
        params = req['context'].path_params
        if params['browseItemType'] is None:
            return text('', 400)
        elif params['browseItemType'] not in enum.BROWSE_API_ITEM_ID:
            return text('Not', 404)
        else:
            return await f(view, req)

    return g


def legal_url_live_programme(f):
    async def g(view, req):
        params = req['context'].path_params
        if params['programSetId'] is None:
            return text('', 400)
        else:
            return await f(view, req)

    return g


def legal_url_channel_programme(f):
    async def g(view, req):
        params = req['context'].path_params
        if params['channelId'] is None:
            return text('', 400)
        else:
            return await f(view, req)

    return g


def legal_url_detail(f):
    async def g(view, req):
        params = req['context'].path_params
        rtype = params['resourceType']
        rid = params['resourceId']

        if rid and (rtype in enum.API_TYPES):
            return await f(view, req)

        return text('Detail resource type is not correct', 404)

    return g
