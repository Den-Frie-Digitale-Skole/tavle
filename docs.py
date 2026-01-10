
from flask import Blueprint
from api import BoardResource

docs_bp = Blueprint('docs_bp', __name__)

@docs_bp.route('/api/docs', methods=['GET'])
def get():
    """Return auto-generated API documentation based on registered resources."""
    docs = {
        'title': 'Whiteboard API',
        'version': '1.0',
        'base_url': '/api',
        'authentication': {
            'type': 'Bearer Token',
            'header': 'Authorization: Bearer <admin_token>',
            'description': 'All endpoints require admin API token authentication'
        },
        'endpoints': []
    }
    
    resource = BoardResource

    # Define resource documentation
    resource_docs = [
        {
            'resource': resource.name,
            'description': resource.desc,
            'endpoints': [
                {
                    'method': 'GET',
                    'path': '/api/boards',
                    'description': 'List all boards',
                    'parameters': [],
                    'response': {
                        'boards': '[array of board objects]',
                        'count': 'number'
                    }
                },
                {
                    'method': 'POST',
                    'path': '/api/boards',
                    'description': 'Create a new board',
                    'parameters': [
                        {'name': 'name', 'type': 'string', 'required': False, 'default': 'Untitled', 'description': 'Board name'}
                    ],
                    'response': {
                        'board': '{board object}',
                        'url': 'string (shareable URL)'
                    }
                },
                {
                    'method': 'GET',
                    'path': '/api/boards/<board_id>',
                    'description': 'Get board details with all strokes and images',
                    'parameters': [
                        {'name': 'board_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Board UUID'}
                    ],
                    'response': {
                        'board': '{board object with strokes/images}',
                        'url': 'string',
                        'stroke_count': 'number',
                        'image_count': 'number'
                    }
                },
                {
                    'method': 'PATCH',
                    'path': '/api/boards/<board_id>',
                    'description': 'Update board (name, active status)',
                    'parameters': [
                        {'name': 'board_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Board UUID'},
                        {'name': 'name', 'type': 'string', 'required': False, 'description': 'New board name'},
                        {'name': 'is_active', 'type': 'boolean', 'required': False, 'description': 'Active status'}
                    ],
                    'response': {
                        'board': '{updated board object}'
                    }
                },
                {
                    'method': 'DELETE',
                    'path': '/api/boards/<board_id>',
                    'description': 'Delete a board and all its contents',
                    'parameters': [
                        {'name': 'board_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Board UUID'}
                    ],
                    'response': {
                        'deleted': 'string (board_id)'
                    }
                },
                {
                    'method': 'POST',
                    'path': '/api/boards/<board_id>/regenerate-token',
                    'description': 'Regenerate access token (invalidates old shareable links)',
                    'parameters': [
                        {'name': 'board_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Board UUID'}
                    ],
                    'response': {
                        'board': '{board object}',
                        'url': 'string (new shareable URL)'
                    }
                }
            ]
        },
        {
            'resource': 'Strokes',
            'description': 'Manage drawing strokes on boards',
            'endpoints': [
                {
                    'method': 'POST',
                    'path': '/api/boards/<board_id>/strokes',
                    'description': 'Create a new stroke',
                    'parameters': [
                        {'name': 'board_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Board UUID'},
                        {'name': 'points', 'type': 'array', 'required': True, 'description': 'Array of point objects [{x, y, pressure}]'},
                        {'name': 'color', 'type': 'string', 'required': False, 'default': '#000000', 'description': 'Stroke color (hex)'},
                        {'name': 'strokeWidth', 'type': 'number', 'required': False, 'default': 4.0, 'description': 'Stroke width'},
                        {'name': 'id', 'type': 'string', 'required': False, 'description': 'Custom stroke ID'},
                        {'name': 'transform', 'type': 'object', 'required': False, 'description': 'Transform matrix'}
                    ],
                    'response': '{stroke object}'
                },
                {
                    'method': 'DELETE',
                    'path': '/api/boards/<board_id>/strokes',
                    'description': 'Clear all strokes from board',
                    'parameters': [
                        {'name': 'board_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Board UUID'}
                    ],
                    'response': {
                        'deleted': 'number (count)'
                    }
                },
                {
                    'method': 'GET',
                    'path': '/api/boards/<board_id>/strokes/<stroke_id>',
                    'description': 'Get a single stroke',
                    'parameters': [
                        {'name': 'board_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Board UUID'},
                        {'name': 'stroke_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Stroke UUID'}
                    ],
                    'response': '{stroke object}'
                },
                {
                    'method': 'PUT',
                    'path': '/api/boards/<board_id>/strokes/<stroke_id>',
                    'description': 'Update a stroke',
                    'parameters': [
                        {'name': 'board_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Board UUID'},
                        {'name': 'stroke_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Stroke UUID'},
                        {'name': 'points', 'type': 'array', 'required': False, 'description': 'Updated points'},
                        {'name': 'color', 'type': 'string', 'required': False, 'description': 'Updated color'},
                        {'name': 'strokeWidth', 'type': 'number', 'required': False, 'description': 'Updated width'},
                        {'name': 'transform', 'type': 'object', 'required': False, 'description': 'Updated transform'}
                    ],
                    'response': '{updated stroke object}'
                },
                {
                    'method': 'DELETE',
                    'path': '/api/boards/<board_id>/strokes/<stroke_id>',
                    'description': 'Delete a stroke',
                    'parameters': [
                        {'name': 'board_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Board UUID'},
                        {'name': 'stroke_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Stroke UUID'}
                    ],
                    'response': {
                        'deleted': 'string (stroke_id)'
                    }
                }
            ]
        },
        {
            'resource': 'Images',
            'description': 'Manage images on boards',
            'endpoints': [
                {
                    'method': 'POST',
                    'path': '/api/boards/<board_id>/images',
                    'description': 'Add a new image to board',
                    'parameters': [
                        {'name': 'board_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Board UUID'},
                        {'name': 'data', 'type': 'string', 'required': True, 'description': 'Base64 encoded image data'},
                        {'name': 'x', 'type': 'number', 'required': False, 'default': 0, 'description': 'X position'},
                        {'name': 'y', 'type': 'number', 'required': False, 'default': 0, 'description': 'Y position'},
                        {'name': 'width', 'type': 'number', 'required': False, 'default': 200, 'description': 'Image width'},
                        {'name': 'height', 'type': 'number', 'required': False, 'default': 200, 'description': 'Image height'},
                        {'name': 'id', 'type': 'string', 'required': False, 'description': 'Custom image ID'},
                        {'name': 'transform', 'type': 'object', 'required': False, 'description': 'Transform matrix'}
                    ],
                    'response': '{image object}'
                },
                {
                    'method': 'DELETE',
                    'path': '/api/boards/<board_id>/images',
                    'description': 'Clear all images from board',
                    'parameters': [
                        {'name': 'board_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Board UUID'}
                    ],
                    'response': {
                        'deleted': 'number (count)'
                    }
                },
                {
                    'method': 'GET',
                    'path': '/api/boards/<board_id>/images/<image_id>',
                    'description': 'Get a single image',
                    'parameters': [
                        {'name': 'board_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Board UUID'},
                        {'name': 'image_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Image UUID'}
                    ],
                    'response': '{image object}'
                },
                {
                    'method': 'PUT',
                    'path': '/api/boards/<board_id>/images/<image_id>',
                    'description': 'Update an image',
                    'parameters': [
                        {'name': 'board_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Board UUID'},
                        {'name': 'image_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Image UUID'},
                        {'name': 'x', 'type': 'number', 'required': False, 'description': 'Updated X position'},
                        {'name': 'y', 'type': 'number', 'required': False, 'description': 'Updated Y position'},
                        {'name': 'width', 'type': 'number', 'required': False, 'description': 'Updated width'},
                        {'name': 'height', 'type': 'number', 'required': False, 'description': 'Updated height'},
                        {'name': 'transform', 'type': 'object', 'required': False, 'description': 'Updated transform'}
                    ],
                    'response': '{updated image object}'
                },
                {
                    'method': 'DELETE',
                    'path': '/api/boards/<board_id>/images/<image_id>',
                    'description': 'Delete an image',
                    'parameters': [
                        {'name': 'board_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Board UUID'},
                        {'name': 'image_id', 'type': 'string', 'required': True, 'in': 'path', 'description': 'Image UUID'}
                    ],
                    'response': {
                        'deleted': 'string (image_id)'
                    }
                }
            ]
        }
    ]
    
    docs['resources'] = resource_docs
    
    return docs, 200
