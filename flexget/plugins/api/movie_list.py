from __future__ import unicode_literals, division, absolute_import

import copy
import logging

from flask import jsonify, request

from flexget.api import api, APIResource
from flexget.plugins.api.movie_queue import empty_response
from flexget.plugins.list.movie_list import PluginMovieList as ml

log = logging.getLogger('movie_list')

movie_list_api = api.namespace('movie_list', description='Movie List operations')

base_movie_entry = {
    'type': 'object',
    'properties': {
        'title': {'type': 'string'},
        'url': {'type': 'string'},
        'movie_name': {'type': 'string'},
        'movie_year': {'type': 'integer'}
    },
    'additionalProperties': True,
    'required': ['url'],
    'anyOf': [
        {'required': ['title']},
        {'required': ['movie_name', 'movie_year']}
    ]

}

return_movie_entry = copy.deepcopy(base_movie_entry)
return_movie_entry['properties']['id'] = {'type': 'integer'}
return_movie_entry['properties']['list_name'] = {'type': 'string'}

return_movie_list = {
    'type': 'object',
    'properties': {
        'movies': {
            'type': 'array',
            'items': return_movie_entry
        },
        'number_of_movies': {'type': 'integer'},
        'list_name': {'type': 'string'}
    }
}

base_movie_entry_schema = api.schema('base_movie_entry', base_movie_entry)
return_movie_entry_schema = api.schema('return_movie_entry_schema', return_movie_entry)
movie_list_return_schema = api.schema('movie_list_return_model', return_movie_list)


@movie_list_api.route('/<string:list_name>')
@api.doc(params={'list_name': 'Name of the list'})
class MovieListAPI(APIResource):
    @api.response(code_or_apierror=200, model=movie_list_return_schema)
    def get(self, list_name, session=None):
        ''' Get Movie list entries '''
        # TODO Pagination
        movies = [dict(movie) for movie in ml.get_list(list_name)]
        return jsonify({'movies': movies,
                        'number_of_entries': len(movies),
                        'list_name': list_name})

    @api.validate(base_movie_entry_schema)
    @api.response(201, model=return_movie_entry_schema)
    @api.doc(description="This will create a new list if list name doesn't exist")
    def post(self, list_name, session=None):
        ''' Adds a movie to the list. '''
        data = request.json
        movies = ml.get_list(list_name)

        movie = movies.add(data, session=session)
        return movie, 201

    @api.validate(base_movie_entry_schema)
    @api.response(200, model=empty_response)
    def delete(self, list_name, session=None):
        ''' Remove an movie from the list '''
        data = request.json
        entries = ml.get_list(list_name)
        entries.discard(data)
        return {}
