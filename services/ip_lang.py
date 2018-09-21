from utils import logger
from geoip2 import database as db
from pathlib import Path

reader = None

langs_map = {
    'Tamil Nadu': {'default': ['tamil']},
    'Andhra Pradesh': {'default': ['telugu'], 'Hyderabad': []},
    'Telangana': {'default': ['telugu'], 'Hyderabad': []},
    'Kerala': {'default': ['malayalam']},
    'Karnataka': {'default': ['kannada'], 'Bengaluru': []},
    'Maharashtra': {'default': ['marathi'], 'Mumbai': []},
    'West Bengal': {'default': ['bengali'], 'Kolkata': []},
    'Gujarat': {'default': ['gujarati']},
    'Punjab': {'default': ['punjabi']}
}

async def init_ip_db():
    global reader
    db_file = Path('conf/GeoIP2-City.mmdb')
    if db_file.is_file():
        reader = db.Reader('conf/GeoIP2-City.mmdb')
        logger.info('ip db reader init done')

async def close_ip_db():
    reader and reader.close()

def get_lang_by_ip(req):
    langs = []
    if reader is None:
        return langs

    try:
        response = reader.city(req.ip)
        state = response.subdivisions.most_specific.name
        city = response.city.name

        if state in langs_map:
            langs = langs_map[state].get(city, langs_map[state]['default'])
    finally:
        return langs
    