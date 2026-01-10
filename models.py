"""
Peewee ORM models for the collaborative whiteboard.
SQLite-first design with easy PostgreSQL migration support.
"""
import os
import json
import uuid
from datetime import datetime
from peewee import (
    Model, SqliteDatabase, PostgresqlDatabase,
    CharField, DateTimeField, FloatField, TextField, ForeignKeyField
)
import logging

logger = logging.getLogger(__name__)

# Database configuration - SQLite by default, PostgreSQL via env var
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL and DATABASE_URL.startswith('postgres'):
    # PostgreSQL configuration
    from playhouse.db_url import connect
    db = connect(DATABASE_URL)
else:
    # SQLite configuration (default)
    db = SqliteDatabase('whiteboard.db', pragmas={
        'journal_mode': 'wal',
        'cache_size': -1 * 64000,  # 64MB
        'foreign_keys': 1,
        'ignore_check_constraints': 0,
    })


class BaseModel(Model):
    """Base model with database binding."""
    class Meta:
        database = db


class Document(BaseModel):
    """Represents a whiteboard document/room."""
    id = CharField(primary_key=True, max_length=255)
    name = CharField(max_length=255, default='Untitled')
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'strokes': [stroke.to_dict() for stroke in self.strokes],
            'images': [image.to_dict() for image in self.images]
        }


class Stroke(BaseModel):
    """Represents a single stroke on the whiteboard."""
    id = CharField(primary_key=True, max_length=36)  # UUID
    document = ForeignKeyField(Document, backref='strokes', on_delete='CASCADE')
    points = TextField()  # JSON: [{x, y, pressure}, ...]
    color = CharField(max_length=20, default='#000000')
    stroke_width = FloatField(default=4.0)
    transform = TextField(default='{"x": 0, "y": 0, "scale": 1}')  # JSON: {x, y, scale}
    created_at = DateTimeField(default=datetime.now)

    def get_points(self):
        """Parse points JSON."""
        try:
            return json.loads(self.points) if self.points else []
        except json.JSONDecodeError:
            logger.error(f"Failed to decode points JSON for stroke {self.id}")
            return []
    

    def set_points(self, points_list):
        """Serialize points to JSON."""
        self.points = json.dumps(points_list)

    def get_transform(self):
        """Parse transform JSON."""
        try:
            return json.loads(self.transform) if self.transform else {'x': 0, 'y': 0, 'scale': 1}
        except json.JSONDecodeError:
            logger.error(f"Failed to decode transform JSON for stroke {self.id}")
            return {'x': 0, 'y': 0, 'scale': 1}
    

    def set_transform(self, transform_dict):
        """Serialize transform to JSON."""
        self.transform = json.dumps(transform_dict)

    def to_dict(self):
        return {
            'id': self.id,
            'documentId': self.document_id,
            'points': self.get_points(),
            'color': self.color,
            'strokeWidth': self.stroke_width,
            'transform': self.get_transform(),
            'createdAt': self.created_at.isoformat()
        }

    @classmethod
    def create_new(cls, document_id, points, color='#000000', stroke_width=4.0, transform=None):
        """Create a new stroke with a generated UUID."""
        stroke_id = str(uuid.uuid4())
        stroke = cls(
            id=stroke_id,
            document_id=document_id,
            color=color,
            stroke_width=stroke_width
        )
        stroke.set_points(points)
        if transform:
            stroke.set_transform(transform)
        return stroke

class Image(BaseModel):
    """Represents an image on the whiteboard."""
    id = CharField(primary_key=True, max_length=36)  # UUID
    document = ForeignKeyField(Document, backref='images', on_delete='CASCADE')
    data = TextField()  # Base64 encoded image data
    x = FloatField(default=0)  # Position X
    y = FloatField(default=0)  # Position Y
    width = FloatField(default=200)  # Display width
    height = FloatField(default=200)  # Display height
    transform = TextField(default='{"x": 0, "y": 0, "scale": 1}')  # JSON: {x, y, scale}
    created_at = DateTimeField(default=datetime.now)

    def get_transform(self):
        """Parse transform JSON."""
        return json.loads(self.transform) if self.transform else {'x': 0, 'y': 0, 'scale': 1}

    def set_transform(self, transform_dict):
        """Serialize transform to JSON."""
        self.transform = json.dumps(transform_dict)

    def to_dict(self):
        return {
            'id': self.id,
            'documentId': self.document_id,
            'data': self.data,
            'x': self.x,
            'y': self.y,
            'width': self.width,
            'height': self.height,
            'transform': self.get_transform(),
            'createdAt': self.created_at.isoformat()
        }

    @classmethod
    def create_new(cls, document_id, data, x=0, y=0, width=200, height=200, transform=None):
        """Create a new image with a generated UUID."""
        image_id = str(uuid.uuid4())
        image = cls(
            id=image_id,
            document_id=document_id,
            data=data,
            x=x,
            y=y,
            width=width,
            height=height
        )
        if transform:
            image.set_transform(transform)
        return image


def init_db():
    """Initialize database tables."""
    db.connect(reuse_if_open=True)
    db.create_tables([Document, Stroke, Image], safe=True)


def get_or_create_document(doc_id):
    """Get existing document or create new one."""
    doc, created = Document.get_or_create(id=doc_id)
    return doc
