"""
Main Flask application with SocketIO for real-time collaboration.
"""
import os
from flask import Flask, render_template, redirect, url_for, abort
from flask_socketio import SocketIO, join_room, leave_room, emit
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from api import BoardResource

from models import init_db, get_or_create_document, get_document_by_token, Stroke, Document, Image
from api import api_bp

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Initialize rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

# Initialize SocketIO with eventlet for async support
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Register API blueprint
app.register_blueprint(api_bp)


# =============================================================================
# Public Routes
# =============================================================================

@app.route('/')
@limiter.limit("30 per minute")
def index():
    """Landing page."""
    return render_template('landing.html')



@app.route('/board/<token>')
@app.route('/b/<token>')
@limiter.limit("30 per minute")
def board(token):
    """Render whiteboard for a specific document using access token."""
    doc = get_document_by_token(token)
    if not doc:
        abort(404)
    return render_template('index.html', token_id=token, access_token=token)


@app.route('/get/<token>')
@limiter.limit("30 per minute")
def get_document(token):
    """Redirect to the whiteboard page for the document with the given token."""
    doc = get_document_by_token(token)
    
    if not doc:
        print(f'Document not found for token: {token}')
        abort(404)

    return doc.to_dict()

# =============================================================================
# Socket Events
# =============================================================================

def get_doc_from_token(token):
    """Helper to get document from token, returns (doc, doc_id) or (None, None)."""
    if not token:
        return None, None
    doc = get_document_by_token(token)
    if not doc:
        return None, None
    return doc, doc.id


@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    print('Client connected')


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    print('Client disconnected')


@socketio.on('join')
def handle_join(data):
    """
    Join a document room for real-time collaboration.
    data: { tokenId: string, userId: string, userName: string }
    """
    token = data.get('tokenId')
    user_id = data.get('userId')
    user_name = data.get('userName', 'Anonymous')
    
    doc, doc_id = get_doc_from_token(token)
    if not doc:
        emit('error', {'message': 'Invalid token'})
        return
    
    # Use token as room ID (more secure than doc_id)
    join_room(token)
    emit('joined', {'tokenId': token, 'message': f'Joined room'})
    print(f'Client {user_name} ({user_id}) joined room: {token[:10]}...')
    
    # Notify others that a user joined
    if user_id:
        emit('user-joined', {
            'userId': user_id,
            'userName': user_name
        }, to=token, include_self=False)


@socketio.on('leave')
def handle_leave(data):
    """
    Leave a document room.
    data: { tokenId: string, userId: string }
    """
    token = data.get('tokenId')
    user_id = data.get('userId')
    
    if token:
        leave_room(token)
        print(f'Client {user_id} left room: {token[:10]}...')
        
        # Notify others that a user left
        if user_id:
            emit('user-left', {
                'userId': user_id
            }, to=token, include_self=False)


@socketio.on('cursor-move')
def handle_cursor_move(data):
    """
    Broadcast cursor position to other users in the room.
    data: { tokenId, userId, userName, cursor: {x, y} }
    """
    token = data.get('tokenId')
    if token:
        emit('remote-cursor', data, to=token, include_self=False)


@socketio.on('stroke-point')
def handle_stroke_point(data):
    """
    Broadcast a stroke point to other users in the room.
    data: { tokenId, point: {x, y, pressure}, color, strokeWidth, strokeId }
    """
    token = data.get('tokenId')
    if token:
        emit('remote-stroke-point', data, to=token, include_self=False)


@socketio.on('stroke-complete')
def handle_stroke_complete(data):
    """
    Broadcast completed stroke and persist to database.
    data: { tokenId, strokeId, points: [{x, y, pressure}], color, strokeWidth, transform }
    """
    token = data.get('tokenId')
    doc, doc_id = get_doc_from_token(token)
    
    if doc:
        # Persist stroke to database
        try:
            stroke = Stroke.create_new(
                document_id=doc_id,
                points=data.get('points', []),
                color=data.get('color', '#000000'),
                stroke_width=data.get('strokeWidth', 4.0),
                transform=data.get('transform')
            )
            stroke.id = data.get('strokeId', stroke.id)
            stroke.save(force_insert=True)
            
            # Update document
            doc.save()
        except Exception as e:
            print(f'Error saving stroke: {e}')
        
        # Broadcast to others
        emit('remote-stroke-complete', data, to=token, include_self=False)


@socketio.on('stroke-update')
def handle_stroke_update(data):
    """
    Broadcast stroke update (move/transform) and persist.
    data: { tokenId, strokeId, transform: {x, y, scale} }
    """
    token = data.get('tokenId')
    stroke_id = data.get('strokeId')
    doc, doc_id = get_doc_from_token(token)
    
    if doc and stroke_id:
        # Update in database
        try:
            stroke = Stroke.get((Stroke.id == stroke_id) & (Stroke.document_id == doc_id))
            stroke.set_transform(data.get('transform', {'x': 0, 'y': 0, 'scale': 1}))
            stroke.save()
        except Stroke.DoesNotExist:
            print(f'Stroke not found: {stroke_id}')
        except Exception as e:
            print(f'Error updating stroke: {e}')
        
        # Broadcast to others
        emit('remote-stroke-update', data, to=token, include_self=False)


@socketio.on('stroke-delete')
def handle_stroke_delete(data):
    """
    Broadcast stroke deletion and remove from database.
    data: { tokenId, strokeId } or { tokenId, strokeIds: [] }
    """
    token = data.get('tokenId')
    stroke_ids = data.get('strokeIds', [])
    doc, doc_id = get_doc_from_token(token)
    
    # Support single strokeId for backwards compatibility
    if not stroke_ids and data.get('strokeId'):
        stroke_ids = [data.get('strokeId')]
    
    if doc and stroke_ids:
        # Delete from database
        try:
            Stroke.delete().where(
                (Stroke.id.in_(stroke_ids)) & (Stroke.document_id == doc_id)
            ).execute()
        except Exception as e:
            print(f'Error deleting strokes: {e}')
        
        # Broadcast to others
        emit('remote-stroke-delete', {'tokenId': token, 'strokeIds': stroke_ids}, 
             to=token, include_self=False)


@socketio.on('clear')
def handle_clear(data):
    """
    Clear all strokes from a document.
    data: { tokenId }
    """
    token = data.get('tokenId')
    doc, doc_id = get_doc_from_token(token)
    
    if doc:
        # Clear from database
        try:
            Stroke.delete().where(Stroke.document_id == doc_id).execute()
            Image.delete().where(Image.document_id == doc_id).execute()
        except Exception as e:
            print(f'Error clearing strokes: {e}')
        
        # Broadcast to others
        emit('remote-clear', {'tokenId': token}, to=token, include_self=False)


@socketio.on('image-add')
def handle_image_add(data):
    """
    Broadcast image addition and persist to database.
    data: { tokenId, imageId, data, x, y, width, height, transform }
    """
    token = data.get('tokenId')
    doc, doc_id = get_doc_from_token(token)
    
    if doc:
        # Persist image to database
        try:
            image = Image.create_new(
                document_id=doc_id,
                data=data.get('data', ''),
                x=data.get('x', 0),
                y=data.get('y', 0),
                width=data.get('width', 200),
                height=data.get('height', 200),
                transform=data.get('transform')
            )
            image.id = data.get('imageId', image.id)
            image.save(force_insert=True)
            
            # Update document
            doc.save()
        except Exception as e:
            print(f'Error saving image: {e}')
        
        # Broadcast to others
        emit('remote-image-add', data, to=token, include_self=False)


@socketio.on('image-update')
def handle_image_update(data):
    """
    Broadcast image update (move/transform) and persist.
    data: { tokenId, imageId, transform: {x, y, scale}, x, y, width, height }
    """
    token = data.get('tokenId')
    image_id = data.get('imageId')
    doc, doc_id = get_doc_from_token(token)
    
    if doc and image_id:
        # Update in database
        try:
            image = Image.get((Image.id == image_id) & (Image.document_id == doc_id))
            if data.get('transform'):
                image.set_transform(data.get('transform'))
            if data.get('x') is not None:
                image.x = data['x']
            if data.get('y') is not None:
                image.y = data['y']
            if data.get('width') is not None:
                image.width = data['width']
            if data.get('height') is not None:
                image.height = data['height']
            image.save()
        except Image.DoesNotExist:
            print(f'Image not found: {image_id}')
        except Exception as e:
            print(f'Error updating image: {e}')
        
        # Broadcast to others
        emit('remote-image-update', data, to=token, include_self=False)


@socketio.on('image-delete')
def handle_image_delete(data):
    """
    Broadcast image deletion and remove from database.
    data: { tokenId, imageId } or { tokenId, imageIds: [] }
    """
    token = data.get('tokenId')
    image_ids = data.get('imageIds', [])
    doc, doc_id = get_doc_from_token(token)
    
    # Support single imageId for backwards compatibility
    if not image_ids and data.get('imageId'):
        image_ids = [data.get('imageId')]
    
    if doc and image_ids:
        # Delete from database
        try:
            Image.delete().where(
                (Image.id.in_(image_ids)) & (Image.document_id == doc_id)
            ).execute()
        except Exception as e:
            print(f'Error deleting images: {e}')
        
        # Broadcast to others
        emit('remote-image-delete', {'tokenId': token, 'imageIds': image_ids}, 
             to=token, include_self=False)


# =============================================================================
# Application Entry Point
# =============================================================================

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Run with SocketIO
    print('Starting whiteboard server on http://localhost:5050')
    socketio.run(app, host='0.0.0.0', port=5050, debug=True)

