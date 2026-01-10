"""
Peewee ORM models for the collaborative whiteboard.
SQLite-first design with easy PostgreSQL migration support.
Includes connection pooling for production PostgreSQL.
"""
import os
import json
import uuid
import secrets
from datetime import datetime
from peewee import (
    Model, SqliteDatabase,
    CharField, DateTimeField, FloatField, TextField, ForeignKeyField, BooleanField
)
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# Database Configuration
# =============================================================================

DATABASE_URL = os.environ.get('DATABASE_URL')

# Connection pool settings (via environment variables)
DB_MAX_CONNECTIONS = int(os.environ.get('DB_MAX_CONNECTIONS', '32'))
DB_STALE_TIMEOUT = int(os.environ.get('DB_STALE_TIMEOUT', '300'))  # 5 minutes
DB_TIMEOUT = int(os.environ.get('DB_TIMEOUT', '30'))  # 30 seconds

if DATABASE_URL and DATABASE_URL.startswith('postgres'):
    # PostgreSQL with connection pooling for production
    from playhouse.pool import PooledPostgresqlExtDatabase
    from urllib.parse import urlparse
    
    # Parse DATABASE_URL
    parsed = urlparse(DATABASE_URL)
    
    db = PooledPostgresqlExtDatabase(
        parsed.path[1:],  # Remove leading '/' from path
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        max_connections=DB_MAX_CONNECTIONS,
        stale_timeout=DB_STALE_TIMEOUT,
        timeout=DB_TIMEOUT,
        autorollback=True,  # Auto-rollback on connection errors
    )
    
    logger.info(f"PostgreSQL connection pool initialized: max={DB_MAX_CONNECTIONS}, "
                f"stale_timeout={DB_STALE_TIMEOUT}s, timeout={DB_TIMEOUT}s")
else:
    # SQLite configuration (development/testing)
    db = SqliteDatabase('whiteboard.db', pragmas={
        'journal_mode': 'wal',
        'cache_size': -1 * 64000,  # 64MB
        'foreign_keys': 1,
        'ignore_check_constraints': 0,
    })
    
    if DATABASE_URL:
        logger.warning(f"DATABASE_URL set but not PostgreSQL: {DATABASE_URL[:20]}...")


class BaseModel(Model):
    """Base model with database binding."""
    class Meta:
        database = db


class Document(BaseModel):
    """Represents a whiteboard document/room."""
    id = CharField(primary_key=True, max_length=255)
    access_token = CharField(max_length=64, unique=True, index=True)  # Long token for URL access
    name = CharField(max_length=255, default='Untitled')
    is_active = BooleanField(default=True)  # Can be deactivated by admin
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)

    def to_dict(self, include_strokes=True):
        result = {
            'id': self.id,
            'access_token': self.access_token,
            'name': self.name,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }
        if include_strokes:
            result['strokes'] = [stroke.to_dict() for stroke in self.strokes]
            result['images'] = [image.to_dict() for image in self.images]
        return result

    @classmethod
    def create_new(cls, name='Untitled'):
        """Create a new document with generated ID and access token."""
        doc_id = str(uuid.uuid4())
        access_token = secrets.token_urlsafe(32)  # 43 characters, URL-safe
        doc = cls.create(
            id=doc_id,
            access_token=access_token,
            name=name
        )
        return doc

    @classmethod
    def get_by_token(cls, token):
        """Get document by access token."""
        try:
            return cls.get(cls.access_token == token, cls.is_active == True)
        except cls.DoesNotExist:
            return None


class Stroke(BaseModel):
    """Represents a single stroke on the whiteboard."""
    id = CharField(primary_key=True, max_length=36)  # UUID
    document = ForeignKeyField(Document, backref='strokes', on_delete='CASCADE')
    points = TextField()  # JSON: [{x, y, pressure}, ...]
    color = CharField(max_length=20, default='#000000')
    stroke_width = FloatField(default=4.0)
    transform = TextField(default='{"x": 0, "y": 0, "scale": 1}')  # JSON: {x, y, scale}
    z_index = FloatField(default=0)  # Z-order for layering (shared with images)
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
            'zIndex': self.z_index,
            'createdAt': self.created_at.isoformat()
        }

    @classmethod
    def create_new(cls, document_id, points, color='#000000', stroke_width=4.0, transform=None, z_index=0):
        """Create a new stroke with a generated UUID."""
        stroke_id = str(uuid.uuid4())
        stroke = cls(
            id=stroke_id,
            document_id=document_id,
            color=color,
            stroke_width=stroke_width,
            z_index=z_index
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
    z_index = FloatField(default=0)  # Z-order for layering (shared with strokes)
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
            'zIndex': self.z_index,
            'createdAt': self.created_at.isoformat()
        }

    @classmethod
    def create_new(cls, document_id, data, x=0, y=0, width=200, height=200, transform=None, z_index=0):
        """Create a new image with a generated UUID."""
        image_id = str(uuid.uuid4())
        image = cls(
            id=image_id,
            document_id=document_id,
            data=data,
            x=x,
            y=y,
            width=width,
            height=height,
            z_index=z_index
        )
        if transform:
            image.set_transform(transform)
        return image


class Settings(BaseModel):
    """
    Key-value settings storage.
    Used for storing application configuration like API keys.
    """
    key = CharField(primary_key=True, max_length=100)
    value = TextField()
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)

    @classmethod
    def get_value(cls, key: str, default: str = None) -> str:
        """Get a setting value by key."""
        try:
            setting = cls.get_by_id(key)
            return setting.value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set_value(cls, key: str, value: str) -> 'Settings':
        """Set a setting value (create or update)."""
        setting, created = cls.get_or_create(key=key, defaults={'value': value})
        if not created:
            setting.value = value
            setting.save()
        return setting


def init_db():
    """Initialize database tables and run migrations."""
    db.connect(reuse_if_open=True)
    db.create_tables([Document, Stroke, Image, Settings], safe=True)
    
    # Run migrations for existing databases
    _run_migrations()


def _run_migrations():
    """Run database migrations for schema updates."""
    # Migration: Add z_index column to Stroke and Image tables
    try:
        # Check if z_index column exists in Stroke table
        cursor = db.execute_sql("PRAGMA table_info(stroke)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'z_index' not in columns:
            logger.info("Migrating: Adding z_index column to Stroke table")
            db.execute_sql("ALTER TABLE stroke ADD COLUMN z_index REAL DEFAULT 0")
    except Exception as e:
        logger.warning(f"Stroke migration check failed (may be PostgreSQL or new DB): {e}")
        # For PostgreSQL, try different syntax
        try:
            db.execute_sql("ALTER TABLE stroke ADD COLUMN IF NOT EXISTS z_index REAL DEFAULT 0")
        except Exception:
            pass  # Column might already exist or DB doesn't support IF NOT EXISTS
    
    try:
        # Check if z_index column exists in Image table
        cursor = db.execute_sql("PRAGMA table_info(image)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'z_index' not in columns:
            logger.info("Migrating: Adding z_index column to Image table")
            db.execute_sql("ALTER TABLE image ADD COLUMN z_index REAL DEFAULT 0")
    except Exception as e:
        logger.warning(f"Image migration check failed (may be PostgreSQL or new DB): {e}")
        # For PostgreSQL, try different syntax
        try:
            db.execute_sql("ALTER TABLE image ADD COLUMN IF NOT EXISTS z_index REAL DEFAULT 0")
        except Exception:
            pass  # Column might already exist or DB doesn't support IF NOT EXISTS


def get_or_create_document(doc_id):
    """Get existing document by ID (legacy support)."""
    try:
        return Document.get_by_id(doc_id)
    except Document.DoesNotExist:
        return None


def get_document_by_token(token):
    """Get document by access token."""
    return Document.get_by_token(token)


# =============================================================================
# Connection Management (for request lifecycle)
# =============================================================================

def open_db_connection():
    """
    Open a database connection (for request start).
    For pooled connections, this acquires from the pool.
    """
    if db.is_closed():
        db.connect(reuse_if_open=True)


def close_db_connection():
    """
    Close database connection (for request end).
    For pooled connections, this returns connection to the pool.
    """
    if not db.is_closed():
        db.close()


def get_pool_status():
    """
    Get connection pool status (PostgreSQL only).
    Returns None for SQLite.
    """
    if hasattr(db, '_in_use') and hasattr(db, '_connections'):
        return {
            'in_use': len(db._in_use),
            'available': len(db._connections),
            'max_connections': DB_MAX_CONNECTIONS,
        }
    return None


def is_postgresql():
    """Check if using PostgreSQL."""
    return DATABASE_URL and DATABASE_URL.startswith('postgres')
