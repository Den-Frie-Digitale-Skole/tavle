"""
Flask-RESTful API for document and stroke management.
"""
from flask import Blueprint
from flask_restful import Api, Resource, reqparse
from models import Document, Stroke, Image, get_or_create_document, db

api_bp = Blueprint('api', __name__, url_prefix='/api')
api = Api(api_bp)


class DocumentResource(Resource):
    """GET /api/docs/<doc_id> - Fetch document with all strokes."""
    
    def get(self, doc_id):
        doc = get_or_create_document(doc_id)
        return doc.to_dict(), 200


class StrokesResource(Resource):
    """
    POST /api/docs/<doc_id>/strokes - Create new stroke
    DELETE /api/docs/<doc_id>/strokes - Clear all strokes
    """
    
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('id', type=str, required=False)
        self.parser.add_argument('points', type=list, location='json', required=True)
        self.parser.add_argument('color', type=str, default='#000000')
        self.parser.add_argument('strokeWidth', type=float, default=4.0)
        self.parser.add_argument('transform', type=dict, location='json', required=False)
        super().__init__()
    
    def post(self, doc_id):
        args = self.parser.parse_args()
        doc = get_or_create_document(doc_id)
        
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
    
    def delete(self, doc_id):
        """Clear all strokes from document."""
        doc = get_or_create_document(doc_id)
        deleted_count = Stroke.delete().where(Stroke.document == doc).execute()
        doc.save()
        
        return {'deleted': deleted_count}, 200


class StrokeResource(Resource):
    """
    GET /api/docs/<doc_id>/strokes/<stroke_id> - Get single stroke
    PUT /api/docs/<doc_id>/strokes/<stroke_id> - Update stroke
    DELETE /api/docs/<doc_id>/strokes/<stroke_id> - Delete stroke
    """
    
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('transform', type=dict, location='json', required=False)
        self.parser.add_argument('points', type=list, location='json', required=False)
        self.parser.add_argument('color', type=str, required=False)
        self.parser.add_argument('strokeWidth', type=float, required=False)
        super().__init__()
    
    def get(self, doc_id, stroke_id):
        try:
            stroke = Stroke.get((Stroke.id == stroke_id) & (Stroke.document_id == doc_id))
            return stroke.to_dict(), 200
        except Stroke.DoesNotExist:
            return {'error': 'Stroke not found'}, 404
    
    def put(self, doc_id, stroke_id):
        args = self.parser.parse_args()
        
        try:
            stroke = Stroke.get((Stroke.id == stroke_id) & (Stroke.document_id == doc_id))
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
        doc = Document.get_by_id(doc_id)
        doc.save()
        
        return stroke.to_dict(), 200
    
    def delete(self, doc_id, stroke_id):
        try:
            stroke = Stroke.get((Stroke.id == stroke_id) & (Stroke.document_id == doc_id))
            stroke.delete_instance()
            
            # Update document's updated_at
            doc = Document.get_by_id(doc_id)
            doc.save()
            
            return {'deleted': stroke_id}, 200
        except Stroke.DoesNotExist:
            return {'error': 'Stroke not found'}, 404


# Register resources
api.add_resource(DocumentResource, '/docs/<string:doc_id>')
api.add_resource(StrokesResource, '/docs/<string:doc_id>/strokes')
api.add_resource(StrokeResource, '/docs/<string:doc_id>/strokes/<string:stroke_id>')


class ImagesResource(Resource):
    """
    POST /api/docs/<doc_id>/images - Create new image
    DELETE /api/docs/<doc_id>/images - Clear all images
    """
    
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
    
    def post(self, doc_id):
        args = self.parser.parse_args()
        doc = get_or_create_document(doc_id)
        
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
    
    def delete(self, doc_id):
        """Clear all images from document."""
        doc = get_or_create_document(doc_id)
        deleted_count = Image.delete().where(Image.document == doc).execute()
        doc.save()
        
        return {'deleted': deleted_count}, 200


class ImageResource(Resource):
    """
    GET /api/docs/<doc_id>/images/<image_id> - Get single image
    PUT /api/docs/<doc_id>/images/<image_id> - Update image
    DELETE /api/docs/<doc_id>/images/<image_id> - Delete image
    """
    
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('transform', type=dict, location='json', required=False)
        self.parser.add_argument('x', type=float, required=False)
        self.parser.add_argument('y', type=float, required=False)
        self.parser.add_argument('width', type=float, required=False)
        self.parser.add_argument('height', type=float, required=False)
        super().__init__()
    
    def get(self, doc_id, image_id):
        try:
            image = Image.get((Image.id == image_id) & (Image.document_id == doc_id))
            return image.to_dict(), 200
        except Image.DoesNotExist:
            return {'error': 'Image not found'}, 404
    
    def put(self, doc_id, image_id):
        args = self.parser.parse_args()
        
        try:
            image = Image.get((Image.id == image_id) & (Image.document_id == doc_id))
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
        doc = Document.get_by_id(doc_id)
        doc.save()
        
        return image.to_dict(), 200
    
    def delete(self, doc_id, image_id):
        try:
            image = Image.get((Image.id == image_id) & (Image.document_id == doc_id))
            image.delete_instance()
            
            # Update document's updated_at
            doc = Document.get_by_id(doc_id)
            doc.save()
            
            return {'deleted': image_id}, 200
        except Image.DoesNotExist:
            return {'error': 'Image not found'}, 404


# Register image resources
api.add_resource(ImagesResource, '/docs/<string:doc_id>/images')
api.add_resource(ImageResource, '/docs/<string:doc_id>/images/<string:image_id>')
