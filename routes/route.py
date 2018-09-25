import sanic
import handlers
from utils.log import print_excp
from sanic.response import text
from sanic.handlers import ErrorHandler
from sanic.exceptions import NotFound
from .middleware import append_logid, header_protect, append_req_context, append_headers, \
    append_user, mark_req_start_time, mark_req_end_time, gzip_res
from conf import route_map


class ExceptionHandler(ErrorHandler):
    def default(self, request, exception: Exception):
        if not isinstance(exception, NotFound):
            print_excp(exception)
            return text("", 500)
        else:
            return text("", 404)


def settle(app: sanic.Sanic):
    app.error_handler = ExceptionHandler()
    app.middleware('request')(append_logid)
    app.middleware('request')(mark_req_start_time)
    app.middleware('request')(header_protect)
    app.middleware('request')(append_req_context)
    app.middleware('request')(append_user)
    app.middleware('request')(append_headers)
    app.middleware('response')(mark_req_end_time)
    app.middleware('response')(gzip_res)

    app.add_route(handlers.HealthView.as_view(), '/')
    app.add_route(handlers.HealthView.as_view(), '/health')
    add_route(app, route_map.MOBIE_FLOW)
    add_route(app, route_map.TEST_MOBILE_FLOW)
    add_route(app, route_map.GAS_CARD_ACCOUNT_INFO)
    add_route(app, route_map.GAS_CARD_PAYBILL)


def add_route(app, obj):
    app.add_route(obj[0], obj[1])
