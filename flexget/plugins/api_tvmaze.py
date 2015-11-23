from __future__ import unicode_literals, division, absolute_import

import logging
from datetime import datetime

from dateutil import parser
from pytvmaze import get_show
from pytvmaze.exceptions import ShowNotFound
from sqlalchemy import Column, Integer, DateTime, String, Unicode, ForeignKey, Numeric, PickleType, func, Table, or_
from sqlalchemy.orm import relation

from flexget import db_schema, plugin
from flexget.event import event
from flexget.utils.database import with_session
from flexget.utils.tools import split_title_year

log = logging.getLogger('api_tvmaze')

DB_VERSION = 0
Base = db_schema.versioned_base('tvmaze', DB_VERSION)
UPDATE_INTERVAL = 7  # Used for expiration, number is in days


class TVMazeGenre(Base):
    __tablename__ = 'tvmaze_genres'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Unicode, unique=True)


genres_table = Table('tvmaze_series_genres', Base.metadata,
                     Column('series_id', Integer, ForeignKey('tvmaze_series.tvmaze_id')),
                     Column('genre_id', Integer, ForeignKey('tvmaze_genres.id')))


class TVMazeLookup(Base):
    __tablename__ = 'tvmaze_lookup'

    id = Column(Integer, primary_key=True, autoincrement=True)
    search_name = Column(Unicode, index=True, unique=True)
    series_id = Column(Integer, ForeignKey('tvmaze_series.tvmaze_id'))
    series = relation('TVMazeSeries', backref='search_strings')


class TVMazeSeries(Base):
    __tablename__ = 'tvmaze_series'

    tvmaze_id = Column(Integer, primary_key=True)
    status = Column(Unicode)
    rating = Column(Numeric)
    genres = relation(TVMazeGenre, secondary=genres_table)
    weight = Column(Integer)
    updated = Column(DateTime)  # last time show was updated at tvmaze
    name = Column(Unicode)
    language = Column(Unicode)
    schedule = Column(PickleType)
    url = Column(String)
    original_image = Column(String)
    medium_image = Column(String)
    tvdb_id = Column(Integer)
    tvrage_id = Column(Integer)
    premiered = Column(DateTime)
    summary = Column(Unicode)
    webchannel = Column(String)
    runtime = Column(Integer)
    show_type = Column(String)
    network = Column(Unicode)
    episodes = relation('TVMazeEpisodes', order_by='TVMazeEpisodes.season', cascade='all, delete, delete-orphan',
                        backref='series')
    last_update = Column(DateTime)  # last time we updated the db for the show

    def __init__(self, series, session):
        self.tvmaze_id = series.maze_id
        self.update(series, session)

    def update(self, series, session):
        self.status = series.status
        self.rating = series.rating['average']
        self.weight = series.weight
        self.updated = datetime.fromtimestamp(series.updated)
        self.name = series.name
        self.language = series.language
        self.schedule = series.schedule
        self.url = series.url
        try:
            self.original_image = series.image.get('original')
        except AttributeError:
            self.original_image = None
        try:
            self.medium_image = series.image.get('medium')
        except AttributeError:
            self.medium_image = None
        self.tvdb_id = series.externals.get('thetvdb')
        self.tvrage_id = series.externals.get('tvrage')
        self.premiered = parser.parse(series.premiered)
        self.summary = series.summary
        self.webchannel = series.webChannel
        self.runtime = series.runtime
        self.show_type = series.type
        self.network = series.network['name']
        self.last_update = datetime.now()

        self.genres[:] = get_db_genres(series.genres, session)

    def __repr__(self):
        return '<TVMazeSeries(title=%s,id=%s,last_update=%s)>' % (self.name, self.id, self.last_update)

    def __str__(self):
        return self.name

    @property
    def expired(self):
        if not self.last_update:
            log.debug('no last update attribute, series set for update')
            return True
        time_dif = datetime.now() - self.last_update
        expiration = time_dif.days > UPDATE_INTERVAL
        log.debug('series {0} is expired: {1}'.format(self.name, expiration))
        return expiration


class TVMazeEpisodes(Base):
    __tablename__ = 'tvmaze_episode'

    tvmaze_id = Column(Integer, primary_key=True)
    series_id = Column(Integer, ForeignKey('tvmaze_series.tvmaze_id'), nullable=False)
    title = Column(Unicode)
    airdate = Column(DateTime)
    url = Column(String)
    number = Column(Integer)
    season_number = Column(Integer)
    original_image = Column(String)
    medium_image = Column(String)
    airstamp = Column(DateTime)
    runtime = Column(Integer)
    season = Column(Integer)
    last_update = Column(DateTime)

    def __init__(self, episode, season_num, series_id):
        self.series_id = series_id
        self.tvmaze_id = episode.maze_id
        self.season = season_num
        self.update(episode)

    def update(self, episode):
        self.title = episode.title
        try:
            self.airdate = datetime.strptime(episode.airdate, '%Y-%m-%d')
        except ValueError:
            self.airdate = None
        self.url = episode.url
        self.number = episode.episode_number
        self.season_number = episode.season_number
        try:
            self.original_image = episode.image.get('original')
        except AttributeError:
            self.original_image = None
        try:
            self.medium_image = episode.image.get('medium')
        except AttributeError:
            self.medium_image = None
        self.airstamp = parser.parse(episode.airstamp)
        self.runtime = episode.runtime
        self.last_update = datetime.now()


def get_db_episodes(seasons, session, series_id):
    db_episodes = []
    for season_num, seas in seasons.items():
        for episode_num, ep in seas.episodes.items():
            db_episode = session.query(TVMazeEpisodes).filter(TVMazeEpisodes.tvmaze_id == ep.maze_id).first()
            if not db_episode:
                log.debug('creating new episode in db. ep_num:{0} season_num:{1} series_id:{2}'.format(episode_num,
                                                                                                       season_num,
                                                                                                       series_id))
                db_episode = TVMazeEpisodes(episode=ep, season_num=season_num, series_id=series_id)
                session.add(db_episode)
            db_episodes.append(db_episode)
    return db_episodes


def get_db_genres(genres, session):
    """Takes a list of genres as strings, returns the database instances for them."""
    db_genres = []
    for genre in genres:
        db_genre = session.query(TVMazeGenre).filter(TVMazeGenre.name == genre).first()
        if not db_genre:
            db_genre = TVMazeGenre(name=genre)
            session.add(db_genre)
        db_genres.append(db_genre)
    return db_genres


def search_params_for_series(**lookup_params):
    search_params = {
        'tvmaze_id': lookup_params.get('maze_id', lookup_params.get('tvmaze_id')),
        'tvdb_id': lookup_params.get('tvdb_id'),
        'tvrage_id': lookup_params.get('tvrage_id'),
        'name': lookup_params.get('title') or lookup_params.get('series_name')
    }
    return search_params


@with_session
def from_cache(session=None, search_params=None, cache_type=None):
    """
    Returns a result from requested table based on search params
    :param session: Current session
    :param search_params: Relevant search params. Should match table column names
    :param cache_type: Object for search
    :return: Query result
    """
    result = None
    if not any(search_params.values()):
        raise LookupError('No parameters sent for cache lookup')
    else:
        log.debug('searching db {0} for the values {1}'.format(cache_type.__tablename__, search_params.items()))
        result = session.query(cache_type).filter(
            or_(getattr(cache_type, col) == val for col, val in search_params.iteritems() if val)).first()
    return result


@with_session
def from_lookup(session=None, title=None):
    log.debug('searching lookup table using title {0}'.format(title))
    return session.query(TVMazeLookup).filter(func.lower(TVMazeLookup.search_name) == title.lower()).first()


def prepare_lookup(**lookup_params):
    """
    Return a dict of params which is valid with pytvmaze get_show method
    """
    prepared_params = {}
    series_name = lookup_params.get('series_name', lookup_params.get('show_name'))
    title, year_match = split_title_year(series_name)

    prepared_params['maze_id'] = lookup_params.get('tvmaze_id')
    prepared_params['tvdb_id'] = lookup_params.get('tvdb_id') or lookup_params.get('trakt_series_tvdb_id')
    prepared_params['tvrage_id'] = lookup_params.get('tvrage_id') or lookup_params.get('trakt_series_tvrage_id')
    prepared_params['show_name'] = title
    prepared_params['show_year'] = lookup_params.get('trakt_series_year') or lookup_params.get('year') or \
                                   lookup_params.get('imdb_year') or year_match
    prepared_params['show_network'] = lookup_params.get('network') or lookup_params.get('trakt_series_network')
    prepared_params['show_country'] = lookup_params.get('country') or lookup_params.get('trakt_series_country')
    prepared_params['show_language'] = lookup_params.get('language')

    return prepared_params


@with_session
def populate_episodes(series_object=None, show_data=None, session=None):
    series = series_object
    series.episodes = get_db_episodes(show_data.seasons, session, series.tvmaze_id)
    return series


class APITVMaze(object):
    @staticmethod
    @with_session
    def series_lookup(session=None, force_cache=False, **lookup_params):
        search_params = search_params_for_series(**lookup_params)
        # Searching cache first
        series = from_cache(session=session, cache_type=TVMazeSeries, search_params=search_params)

        # Preparing search from lookup table
        title = lookup_params.get('series_name') or lookup_params.get('show_name') or lookup_params.get('title')
        if not series and title:
            search = from_lookup(session=session, title=title)
            if search and search.series:
                series = search.series

        if force_cache:
            if series:  # If force_cache is True, return series even if it expired
                log.debug('forcing cache for series {0}'.format(series.name))
                return series
            raise LookupError('Series %s not found from cache' % lookup_params)
        if series and not series.expired:
            log.debug('returning series {0} from cache'.format(series.name))
            return series

        prepared_params = prepare_lookup(**lookup_params)
        try:
            log.debug('trying to fetch series {0} from pytvmaze'.format(title))
            pytvmaze_show = get_show(**prepared_params)
        except ShowNotFound:
            log.debug('could not find series {0} in pytvmaze'.format(title))
            return

        # See if series already exist in cache
        series = session.query(TVMazeSeries).filter(TVMazeSeries.tvmaze_id == pytvmaze_show.maze_id).first()
        if series:
            log.debug('found expired series {0}, refreshing data.'.format(series.name))
            series.update(pytvmaze_show, session)
            series = populate_episodes(series_object=series, show_data=pytvmaze_show, session=session)
            session.flush()
        else:
            log.debug('creating new series {0} in tvmaze_series db'.format(title))
            series = TVMazeSeries(pytvmaze_show, session)
            series = populate_episodes(series_object=series, show_data=pytvmaze_show, session=session)
            session.add(series)
        # If there's a mismatch between actual series name and requested title,
        # add it to lookup table for future lookups
        if series and title.lower() != series.name.lower():
            log.debug('mismatch between series title and search title. saving in lookup table')
            session.add(TVMazeLookup(search_name=title, series=series))
        return series

    @staticmethod
    @with_session
    def episode_lookup(session=None, force_cache=False, **lookup_params):
        series_name = lookup_params.get('series_name')
        season_number = lookup_params.get('series_season')
        episode_number = lookup_params.get('series_episode')
        if not all([season_number, episode_number, series_name]):
            raise LookupError('Not enough parameter to lookup episode')
        series = APITVMaze.series_lookup(session=session, force_cache=force_cache, **lookup_params)
        if not series:
            raise LookupError('Could not find series with the following parameters: {0}'.format(**lookup_params))
        for episode in series.episodes:
            if episode.season_number == season_number and episode.number == episode_number:
                return episode
        return


@event('plugin.register')
def register_plugin():
    plugin.register(APITVMaze, 'api_tvmaze', api_ver=2)