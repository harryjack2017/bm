import ujson
from abc import ABC, abstractmethod
from utils import logger


class BaseModel(ABC):
    def __init__(self, req):
        self.req = req

    @property
    def xdensity(self):
        return self.req['xheaders']['density']

    @property
    def is_login(self):
        return self.req['user'].is_login

    @property
    def uid(self):
        return self.req['user'].id

    def format_posters(self, posterList):
        if not posterList:
            return []

        selfPics = ujson.loads(posterList)
        if len(selfPics) <= 0:
            return []

        selfPic = min(selfPics, key=lambda it: abs(float(it.get('density', '1x')[:-1]) - float(self.xdensity)))
        res_density = selfPic.get('density', '1x')
        posters = [{
            'width': it.get('width') or 0,
            'url': f"{get_cdn_address(enum.PIC_SERVER_URL, picture=True)}/{it.get('url', '').strip('/')}",
            'height': it.get('height') or 0
        } for it in selfPics if it.get('density', '1x') == res_density]

        return posters

    def select_icon(self, posters):
        for poster in posters:
            if int(poster.get('width')) == int(poster.get('height')):
                return poster.get('url')

        for poster in posters:
            if (int(poster.get('width')) / int(poster.get('height'))) == (16/9):
                return poster.get('url')

        return ''

    def log(self, log_info):
        try:
            body = dict({
                'user_id': self.uid,
            }, **log_info)
            # asyncio.get_event_loop().create_task(send_log(body))

        except Exception as e:
            logger.error(e)

    @abstractmethod
    async def render(self):
        pass

    @abstractmethod
    def format(self):
        pass
