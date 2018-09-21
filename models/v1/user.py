from jwt import encode, decode, DecodeError
from uuid import uuid4
import time
import ujson
from utils import logger
from conf import conf, enum


class User():
    '''@service is the address of backend Auth server'''

    def __init__(self, req, service):
        self._uid = None
        self._jwt = None
        self._profile = None
        self._address = service
        self._utype = None
        self.is_login = False  # 用户的authorization是否合法
        uuid = req.headers.get('X-Client-Id')
        if uuid is None:
            # convert uuid to string
            uuid = str(uuid4())
        self._uuid = uuid
        jwt = req.headers.get('Authorization')
        if jwt is not None:
            try:
                # convert jwt to bytes to decode
                jwt = jwt.encode()
                payload = decode(jwt, self.secret, algorithms=self.hash_algo)
            except DecodeError as err:
                # log error
                logger.debug(err)
                jwt = None
            else:
                uid = payload.get('id')
                # self.creatime = payload.get('creatime')
                if uid is not None:
                    self._uid = uid
                    self._utype = uid[1:3]
                    self.is_login = True
        self._jwt = jwt

    async def login(self, token, type='facebook'):
        utype = self.party_abbr_map.get(type)
        if utype is None:
            return
        # ask Auth to authenticate token
        data_profile = await post_user_login({'type': type, 'token': token, 'msg': 'login'})
        self._profile = ujson.loads(data_profile) if data_profile else None
        if self._profile is not None:
            self._uid = self._profile.get('id')
            self._utype = utype
            if self._jwt is None and self._uid is not None:
                jwt = encode({'id': self._uid, 'creatime': int((time.time() + time.timezone))}, self.secret,
                             algorithm=self.hash_algo)
                # convert bytes to string to set cookies
                self._jwt = jwt.decode()

    @property
    def id(self):
        if self._uid is not None:
            return self._uid
        else:
            return self._uuid

    @property
    def profile(self):
        if self._profile is not None and self._uid is not None:
            lang = self._profile['settings'].get('lang')
            if type(lang) == str:
                set_lang = []
                if len(lang) > 0:
                    set_lang = lang.split(';')
                self._profile['settings']['lang'] = [enum.ABBR_LANG_MAPPING[l] for l in set_lang if l in enum.ABBR_LANG_MAPPING]
            del_array = ['app_version', 'bundleid', 'autoplay', 'devicetokens', 'notification']
            for i in del_array:
                if self._profile['settings'].__contains__(i):
                    del self._profile['settings'][i]
            return {
                **self._profile,
                'token': self._jwt
            }

    @property
    def hash_algo(self):
        return 'HS256'

    @property
    def secret(self):
        return conf.USER_SECRET

    @property
    def party_abbr_map(self):
        return {
            'facebook': 'fb'
        }

    @property
    def uuid(self):
        return self._uuid
