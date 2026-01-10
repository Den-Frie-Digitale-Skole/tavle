"""
Main Flask application with SocketIO for real-time collaboration.
"""
import os
from flask import Flask, render_template, redirect, url_for, request
from flask_socketio import SocketIO, join_room, leave_room, emit

from models import init_db, get_or_create_document, Stroke, Document, Image
from api import api_bp

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Initialize SocketIO with eventlet for async support
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Register API blueprint
app.register_blueprint(api_bp)


# =============================================================================
# Routes
# =============================================================================

@app.route('/')
def index():
    """Redirect to a default document."""
    return redirect(url_for('document', doc_id='default'))


@app.route('/doc/<doc_id>')
def document(doc_id):
    """Render whiteboard for a specific document."""
    # Ensure document exists
    get_or_create_document(doc_id)
    return render_template('index.html', document_id=doc_id)


# =============================================================================
# Socket Events
# =============================================================================

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
    data: { documentId: string }
    """
    doc_id = data.get('documentId')
    if doc_id:
        join_room(doc_id)
        emit('joined', {'documentId': doc_id, 'message': f'Joined room {doc_id}'})
        print(f'Client joined room: {doc_id}')


@socketio.on('leave')
def handle_leave(data):
    """
    Leave a document room.
    data: { documentId: string }
    """
    doc_id = data.get('documentId')
    if doc_id:
        leave_room(doc_id)
        print(f'Client left room: {doc_id}')


@socketio.on('stroke-point')
def handle_stroke_point(data):
    """
    Broadcast a stroke point to other users in the room.
    data: { documentId, point: {x, y, pressure}, color, strokeWidth, strokeId }
    """
    doc_id = data.get('documentId')
    if doc_id:
        emit('remote-stroke-point', data, to=doc_id, include_self=False)


@socketio.on('stroke-complete')
def handle_stroke_complete(data):
    """
    Broadcast completed stroke and persist to database.
    data: { documentId, strokeId, points: [{x, y, pressure}], color, strokeWidth, transform }
    """
    doc_id = data.get('documentId')
    if doc_id:
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
            doc = Document.get_by_id(doc_id)
            doc.save()
        except Exception as e:
            print(f'Error saving stroke: {e}')
        
        # Broadcast to others
        emit('remote-stroke-complete', data, to=doc_id, include_self=False)


@socketio.on('stroke-update')
def handle_stroke_update(data):
    """
    Broadcast stroke update (move/transform) and persist.
    data: { documentId, strokeId, transform: {x, y, scale} }
    """
    doc_id = data.get('documentId')
    stroke_id = data.get('strokeId')
    
    if doc_id and stroke_id:
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
        emit('remote-stroke-update', data, to=doc_id, include_self=False)


@socketio.on('stroke-delete')
def handle_stroke_delete(data):
    """
    Broadcast stroke deletion and remove from database.
    data: { documentId, strokeId } or { documentId, strokeIds: [] }
    """
    doc_id = data.get('documentId')
    stroke_ids = data.get('strokeIds', [])
    
    # Support single strokeId for backwards compatibility
    if not stroke_ids and data.get('strokeId'):
        stroke_ids = [data.get('strokeId')]
    
    if doc_id and stroke_ids:
        # Delete from database
        try:
            Stroke.delete().where(
                (Stroke.id.in_(stroke_ids)) & (Stroke.document_id == doc_id)
            ).execute()
        except Exception as e:
            print(f'Error deleting strokes: {e}')
        
        # Broadcast to others
        emit('remote-stroke-delete', {'documentId': doc_id, 'strokeIds': stroke_ids}, 
             to=doc_id, include_self=False)


@socketio.on('clear')
def handle_clear(data):
    """
    Clear all strokes from a document.
    data: { documentId }
    """
    doc_id = data.get('documentId')
    
    if doc_id:
        # Clear from database
        try:
            Stroke.delete().where(Stroke.document_id == doc_id).execute()
            Image.delete().where(Image.document_id == doc_id).execute()
        except Exception as e:
            print(f'Error clearing strokes: {e}')
        
        # Broadcast to others
        emit('remote-clear', {'documentId': doc_id}, to=doc_id, include_self=False)


@socketio.on('image-add')
def handle_image_add(data):
    """
    Broadcast image addition and persist to database.
    data: { documentId, imageId, data, x, y, width, height, transform }
    """
    doc_id = data.get('documentId')
    if doc_id:
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
            doc = Document.get_by_id(doc_id)
            doc.save()
        except Exception as e:
            print(f'Error saving image: {e}')
        
        # Broadcast to others
        emit('remote-image-add', data, to=doc_id, include_self=False)


@socketio.on('image-update')
def handle_image_update(data):
    """
    Broadcast image update (move/transform) and persist.
    data: { documentId, imageId, transform: {x, y, scale}, x, y, width, height }
    """
    doc_id = data.get('documentId')
    image_id = data.get('imageId')
    
    if doc_id and image_id:
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
        emit('remote-image-update', data, to=doc_id, include_self=False)


@socketio.on('image-delete')
def handle_image_delete(data):
    """
    Broadcast image deletion and remove from database.
    data: { documentId, imageId } or { documentId, imageIds: [] }
    """
    doc_id = data.get('documentId')
    image_ids = data.get('imageIds', [])
    
    # Support single imageId for backwards compatibility
    if not image_ids and data.get('imageId'):
        image_ids = [data.get('imageId')]
    
    if doc_id and image_ids:
        # Delete from database
        try:
            Image.delete().where(
                (Image.id.in_(image_ids)) & (Image.document_id == doc_id)
            ).execute()
        except Exception as e:
            print(f'Error deleting images: {e}')
        
        # Broadcast to others
        emit('remote-image-delete', {'documentId': doc_id, 'imageIds': image_ids}, 
             to=doc_id, include_self=False)


# =============================================================================
# Application Entry Point
# =============================================================================

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Run with SocketIO
    print('Starting whiteboard server on http://localhost:5050')
    socketio.run(app, host='0.0.0.0', port=5050, debug=True)

