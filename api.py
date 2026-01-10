"""
Flask-RESTful API for document and stroke management.
All endpoints require admin API token authentication.
"""
import os
import secrets
from functools import wraps
from flask import Blueprint, request, url_for
from flask_restful import Api, Resource, reqparse
from models import Document, Stroke, Image, get_or_create_document, db
from setup import get_admin_token

api_bp = Blueprint('api', __name__, url_prefix='/api')
api = Api(api_bp)


def get_current_admin_token():
    """Get the current admin API token (called per-request to allow config reload)."""
    return get_admin_token()


def require_admin_token(f):
    """Decorator to require admin API token for a method."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return {'error': 'Missing Authorization header'}, 401
        
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return {'error': 'Invalid Authorization header format'}, 401
        
        if parts[1] != get_current_admin_token():
            return {'error': 'Invalid API token'}, 403
        
        return f(*args, **kwargs)
    return decorated


def get_document_or_404(doc_id):
    """Get document by ID or return None."""
    try:
        return Document.get_by_id(doc_id)
    except Document.DoesNotExist:
        return None


# =============================================================================
# Board/Document Resources
# =============================================================================

class BoardsResource(Resource):
    """
    GET /api/boards - List all boards
    POST /api/boards - Create new board
    """
    
    method_decorators = [require_admin_token]
    
    def get(self):
        """List all boards."""
        boards = Document.select().order_by(Document.created_at.desc())
        return {
            'boards': [b.to_dict(include_strokes=False) for b in boards],
            'count': boards.count()
        }, 200
    
    def post(self):
        """Create a new board."""
        parser = reqparse.RequestParser()
        parser.add_argument('name', type=str, default='Untitled')
        args = parser.parse_args()
        
        doc = Document.create_new(name=args['name'])
        
        return {
            'board': doc.to_dict(include_strokes=False),
            'url': url_for('board', token=doc.access_token, _external=True)
        }, 201


class BoardResource(Resource):
    """
    GET /api/boards/<board_id> - Get board details (with strokes/images)
    PATCH /api/boards/<board_id> - Update board
    DELETE /api/boards/<board_id> - Delete board
    """
    
    method_decorators = [require_admin_token]
    
    def get(self, board_id):
        """Get board details with all strokes and images."""
        doc = get_document_or_404(board_id)
        if not doc:
            return {'error': 'Board not found'}, 404
        
        return {
            'board': doc.to_dict(include_strokes=True),
            'url': url_for('board', token=doc.access_token, _external=True),
            'stroke_count': doc.strokes.count(),
            'image_count': doc.images.count()
        }, 200
    
    def patch(self, board_id):
        """Update board (name, active status)."""
        doc = get_document_or_404(board_id)
        if not doc:
            return {'error': 'Board not found'}, 404
        
        parser = reqparse.RequestParser()
        parser.add_argument('name', type=str, required=False)
        parser.add_argument('is_active', type=bool, required=False)
        args = parser.parse_args()
        
        if args.get('name') is not None:
            doc.name = args['name']
        if args.get('is_active') is not None:
            doc.is_active = args['is_active']
        
        doc.save()
        
        return {'board': doc.to_dict(include_strokes=False)}, 200
    
    def delete(self, board_id):
        """Delete a board and all its contents."""
        doc = get_document_or_404(board_id)
        if not doc:
            return {'error': 'Board not found'}, 404
        
        # Delete related strokes and images
        Stroke.delete().where(Stroke.document == doc).execute()
        Image.delete().where(Image.document == doc).execute()
        doc.delete_instance()
        
        return {'deleted': board_id}, 200


class BoardTokenResource(Resource):
    """POST /api/boards/<board_id>/regenerate-token - Regenerate access token."""
    
    method_decorators = [require_admin_token]
    
    def post(self, board_id):
        """Regenerate access token for a board (invalidates old links)."""
        doc = get_document_or_404(board_id)
        if not doc:
            return {'error': 'Board not found'}, 404
        
        doc.access_token = secrets.token_urlsafe(32)
        doc.save()
        
        return {
            'board': doc.to_dict(include_strokes=False),
            'url': url_for('board', token=doc.access_token, _external=True)
        }, 200


# =============================================================================
# Stroke Resources
# =============================================================================

class StrokesResource(Resource):
    """
    POST /api/boards/<board_id>/strokes - Create new stroke
    DELETE /api/boards/<board_id>/strokes - Clear all strokes
    """
    
    method_decorators = [require_admin_token]
    
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('id', type=str, required=False)
        self.parser.add_argument('points', type=list, location='json', required=True)
        self.parser.add_argument('color', type=str, default='#000000')
        self.parser.add_argument('strokeWidth', type=float, default=4.0)
        self.parser.add_argument('transform', type=dict, location='json', required=False)
        super().__init__()
    
    def post(self, board_id):
        args = self.parser.parse_args()
        doc = get_document_or_404(board_id)
        if not doc:
            return {'error': 'Board not found'}, 404
        
        stroke = Stroke.create_new(
            document_id=doc.id,
            points=args['points'],
            color=args['color'],
            stroke_width=args['strokeWidth'],
            transform=args.get('transform')
        )
        
        # If client provided an ID, use it
        if args.get('id'):
            stroke.id = args['id']
        
        stroke.save(force_insert=True)
        doc.save()  # Update document's updated_at
        
        return stroke.to_dict(), 201
    
    def delete(self, board_id):
        """Clear all strokes from board."""
        doc = get_document_or_404(board_id)
        if not doc:
            return {'error': 'Board not found'}, 404
        
        deleted_count = Stroke.delete().where(Stroke.document == doc).execute()
        doc.save()
        
        return {'deleted': deleted_count}, 200


class StrokeResource(Resource):
    """
    GET /api/boards/<board_id>/strokes/<stroke_id> - Get single stroke
    PUT /api/boards/<board_id>/strokes/<stroke_id> - Update stroke
    DELETE /api/boards/<board_id>/strokes/<stroke_id> - Delete stroke
    """
    
    method_decorators = [require_admin_token]
    
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('transform', type=dict, location='json', required=False)
        self.parser.add_argument('points', type=list, location='json', required=False)
        self.parser.add_argument('color', type=str, required=False)
        self.parser.add_argument('strokeWidth', type=float, required=False)
        super().__init__()
    
    def get(self, board_id, stroke_id):
        try:
            stroke = Stroke.get((Stroke.id == stroke_id) & (Stroke.document_id == board_id))
            return stroke.to_dict(), 200
        except Stroke.DoesNotExist:
            return {'error': 'Stroke not found'}, 404
    
    def put(self, board_id, stroke_id):
        args = self.parser.parse_args()
        
        try:
            stroke = Stroke.get((Stroke.id == stroke_id) & (Stroke.document_id == board_id))
        except Stroke.DoesNotExist:
            return {'error': 'Stroke not found'}, 404
        
        # Update fields if provided
        if args.get('transform'):
            stroke.set_transform(args['transform'])
        if args.get('points'):
            stroke.set_points(args['points'])
        if args.get('color'):
            stroke.color = args['color']
        if args.get('strokeWidth'):
            stroke.stroke_width = args['strokeWidth']
        
        stroke.save()
        
        # Update document's updated_at
        doc = Document.get_by_id(board_id)
        doc.save()
        
        return stroke.to_dict(), 200
    
    def delete(self, board_id, stroke_id):
        try:
            stroke = Stroke.get((Stroke.id == stroke_id) & (Stroke.document_id == board_id))
            stroke.delete_instance()
            
            # Update document's updated_at
            doc = Document.get_by_id(board_id)
            doc.save()
            
            return {'deleted': stroke_id}, 200
        except Stroke.DoesNotExist:
            return {'error': 'Stroke not found'}, 404


# =============================================================================
# Image Resources
# =============================================================================

class ImagesResource(Resource):
    """
    POST /api/boards/<board_id>/images - Create new image
    DELETE /api/boards/<board_id>/images - Clear all images
    """
    
    method_decorators = [require_admin_token]
    
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('id', type=str, required=False)
        self.parser.add_argument('data', type=str, required=True)  # Base64 image data
        self.parser.add_argument('x', type=float, default=0)
        self.parser.add_argument('y', type=float, default=0)
        self.parser.add_argument('width', type=float, default=200)
        self.parser.add_argument('height', type=float, default=200)
        self.parser.add_argument('transform', type=dict, location='json', required=False)
        super().__init__()
    
    def post(self, board_id):
        args = self.parser.parse_args()
        doc = get_document_or_404(board_id)
        if not doc:
            return {'error': 'Board not found'}, 404
        
        image = Image.create_new(
            document_id=doc.id,
            data=args['data'],
            x=args['x'],
            y=args['y'],
            width=args['width'],
            height=args['height'],
            transform=args.get('transform')
        )
        
        # If client provided an ID, use it
        if args.get('id'):
            image.id = args['id']
        
        image.save(force_insert=True)
        doc.save()  # Update document's updated_at
        
        return image.to_dict(), 201
    
    def delete(self, board_id):
        """Clear all images from board."""
        doc = get_document_or_404(board_id)
        if not doc:
            return {'error': 'Board not found'}, 404
        
        deleted_count = Image.delete().where(Image.document == doc).execute()
        doc.save()
        
        return {'deleted': deleted_count}, 200


class ImageResource(Resource):
    """
    GET /api/boards/<board_id>/images/<image_id> - Get single image
    PUT /api/boards/<board_id>/images/<image_id> - Update image
    DELETE /api/boards/<board_id>/images/<image_id> - Delete image
    """
    
    method_decorators = [require_admin_token]
    
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('transform', type=dict, location='json', required=False)
        self.parser.add_argument('x', type=float, required=False)
        self.parser.add_argument('y', type=float, required=False)
        self.parser.add_argument('width', type=float, required=False)
        self.parser.add_argument('height', type=float, required=False)
        super().__init__()
    
    def get(self, board_id, image_id):
        try:
            image = Image.get((Image.id == image_id) & (Image.document_id == board_id))
            return image.to_dict(), 200
        except Image.DoesNotExist:
            return {'error': 'Image not found'}, 404
    
    def put(self, board_id, image_id):
        args = self.parser.parse_args()
        
        try:
            image = Image.get((Image.id == image_id) & (Image.document_id == board_id))
        except Image.DoesNotExist:
            return {'error': 'Image not found'}, 404
        
        # Update fields if provided
        if args.get('transform'):
            image.set_transform(args['transform'])
        if args.get('x') is not None:
            image.x = args['x']
        if args.get('y') is not None:
            image.y = args['y']
        if args.get('width') is not None:
            image.width = args['width']
        if args.get('height') is not None:
            image.height = args['height']
        
        image.save()
        
        # Update document's updated_at
        doc = Document.get_by_id(board_id)
        doc.save()
        
        return image.to_dict(), 200
    
    def delete(self, board_id, image_id):
        try:
            image = Image.get((Image.id == image_id) & (Image.document_id == board_id))
            image.delete_instance()
            
            # Update document's updated_at
            doc = Document.get_by_id(board_id)
            doc.save()
            
            return {'deleted': image_id}, 200
        except Image.DoesNotExist:
            return {'error': 'Image not found'}, 404


# =============================================================================
# Register all resources
# =============================================================================

# Board resources
api.add_resource(BoardsResource, '/boards')
api.add_resource(BoardResource, '/boards/<string:board_id>')
api.add_resource(BoardTokenResource, '/boards/<string:board_id>/regenerate-token')

# Stroke resources
api.add_resource(StrokesResource, '/boards/<string:board_id>/strokes')
api.add_resource(StrokeResource, '/boards/<string:board_id>/strokes/<string:stroke_id>')

# Image resources
api.add_resource(ImagesResource, '/boards/<string:board_id>/images')
api.add_resource(ImageResource, '/boards/<string:board_id>/images/<string:image_id>')

