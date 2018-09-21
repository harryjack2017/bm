from asyncio import sleep

from sanic.views import HTTPMethodView
from sanic.response import text


class HealthView(HTTPMethodView):
    async def get(self, req):
        from utils import server_state
        while not server_state.ready:
            await sleep(0.1)

        return text('', 200)
