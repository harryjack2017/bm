from sanic import Sanic
from utils import LOGGING_CONFIG, logger
import routes
from conf import conf
from services import http_request, redis_client

app = Sanic(log_config=LOGGING_CONFIG)


async def app_init_tasks(app, loop):
    await redis_client.redis.prepare_conn()

    await http_request.init_session()

    from utils import server_state
    server_state.ready = True


async def app_clean_tasks(app, loop):
    from utils import server_state
    server_state.ready = False

    await http_request.close_session()


if __name__ == '__main__':
    routes.settle(app)
    app.listener('before_server_start')(app_init_tasks)
    app.listener('after_server_start')(lambda app, loop: logger.info(f'Starting server at {conf.PORT}'))
    # app.listener('after_server_stop')(app_clean_tasks)
    app.run(debug=False, workers=1, host='0.0.0.0', port=conf.PORT, access_log=True)
