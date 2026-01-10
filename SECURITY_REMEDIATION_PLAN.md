# 🔒 Security Remediation Plan

**Project:** Collaborative Whiteboard  
**Date:** January 10, 2026  
**Target Users:** 300 daily users  
**Priority:** Production-blocking security fixes

---

## 📋 Overview

This plan addresses all critical, high, and medium security vulnerabilities identified in the security analysis. Tasks are organized by priority and estimated effort.

---

## Phase 1: Critical Fixes (Must Complete Before Production)
**Timeline: 3-5 days**

### 1.1 Server-Side Session Management for WebSocket

**Problem:** Client-provided `tokenId` is trusted in every WebSocket event, allowing cross-board attacks.

**Solution:** Store the user's authorized room server-side when they join.

**File:** `server.py`

```python
# Add at the top, after imports
from flask import request

# Server-side session storage for WebSocket connections
socket_sessions = {}  # sid -> {'token': str, 'user_id': str, 'user_name': str}


def get_session_token(sid=None):
    """Get the authorized token for a socket session."""
    sid = sid or request.sid
    session = socket_sessions.get(sid)
    return session.get('token') if session else None


@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    socket_sessions[request.sid] = {}
    print(f'Client connected: {request.sid}')


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    session = socket_sessions.pop(request.sid, None)
    if session and session.get('token'):
        # Notify others that user left
        emit('user-left', {'userId': session.get('user_id')}, 
             to=session['token'], include_self=False)
    print(f'Client disconnected: {request.sid}')


@socketio.on('join')
def handle_join(data):
    """Join a document room for real-time collaboration."""
    token = data.get('tokenId')
    user_id = data.get('userId')
    user_name = data.get('userName', 'Anonymous')[:50]  # Limit name length
    
    doc, doc_id = get_doc_from_token(token)
    if not doc:
        emit('error', {'message': 'Invalid token'})
        return
    
    # Store session data server-side
    socket_sessions[request.sid] = {
        'token': token,
        'user_id': user_id,
        'user_name': user_name
    }
    
    join_room(token)
    emit('joined', {'tokenId': token, 'message': 'Joined room'})
    # ... rest of handler
```

**Then update ALL other handlers to use server-side token:**

```python
@socketio.on('stroke-complete')
def handle_stroke_complete(data):
    """Broadcast completed stroke and persist to database."""
    # Use server-side token, NOT client-provided
    token = get_session_token()
    if not token:
        emit('error', {'message': 'Not authenticated'})
        return
    
    doc, doc_id = get_doc_from_token(token)
    # ... rest of handler
```

**Affected handlers:**
- `handle_cursor_move`
- `handle_stroke_point`
- `handle_stroke_complete`
- `handle_stroke_update`
- `handle_stroke_delete`
- `handle_clear`
- `handle_image_add`
- `handle_image_update`
- `handle_image_delete`
- `handle_leave`

---

### 1.2 Input Validation Schema

**Problem:** No validation on any user input - coordinates, colors, points, etc.

**Solution:** Create validation schemas using a lightweight approach (no heavy dependencies).

**New File:** `validators.py`

```python
"""
Input validation for WebSocket events and API requests.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

# Constants
MAX_POINTS_PER_STROKE = 10000
MAX_COORDINATE = 100000
MIN_COORDINATE = -100000
MAX_STROKE_WIDTH = 100
MIN_STROKE_WIDTH = 0.5
MAX_IMAGE_DATA_SIZE = 5 * 1024 * 1024  # 5MB base64
MAX_STROKES_PER_BOARD = 10000
MAX_IMAGES_PER_BOARD = 100
MAX_USER_NAME_LENGTH = 50
MAX_STROKE_IDS_PER_DELETE = 100

# Regex patterns
COLOR_PATTERN = re.compile(r'^#[0-9A-Fa-f]{6}$')
UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
DATA_URL_PATTERN = re.compile(r'^data:image/(png|jpeg|jpg|gif|webp);base64,')


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


def validate_color(color: Any) -> str:
    """Validate and sanitize color value."""
    if not isinstance(color, str):
        return '#000000'
    if COLOR_PATTERN.match(color):
        return color.lower()
    return '#000000'


def validate_coordinate(value: Any) -> float:
    """Validate coordinate is a reasonable number."""
    try:
        num = float(value)
        if num != num:  # NaN check
            return 0.0
        return max(MIN_COORDINATE, min(MAX_COORDINATE, num))
    except (TypeError, ValueError):
        return 0.0


def validate_stroke_width(value: Any) -> float:
    """Validate stroke width."""
    try:
        num = float(value)
        if num != num:  # NaN check
            return 4.0
        return max(MIN_STROKE_WIDTH, min(MAX_STROKE_WIDTH, num))
    except (TypeError, ValueError):
        return 4.0


def validate_point(point: Any) -> Optional[Dict]:
    """Validate a single point."""
    if not isinstance(point, dict):
        return None
    
    x = validate_coordinate(point.get('x', 0))
    y = validate_coordinate(point.get('y', 0))
    
    pressure = point.get('pressure', 0.5)
    try:
        pressure = max(0.0, min(1.0, float(pressure)))
    except (TypeError, ValueError):
        pressure = 0.5
    
    return {'x': x, 'y': y, 'pressure': pressure}


def validate_points(points: Any) -> List[Dict]:
    """Validate points array."""
    if not isinstance(points, list):
        return []
    
    validated = []
    for point in points[:MAX_POINTS_PER_STROKE]:
        validated_point = validate_point(point)
        if validated_point:
            validated.append(validated_point)
    
    return validated


def validate_transform(transform: Any) -> Dict:
    """Validate transform object."""
    default = {'x': 0, 'y': 0, 'scale': 1}
    if not isinstance(transform, dict):
        return default
    
    return {
        'x': validate_coordinate(transform.get('x', 0)),
        'y': validate_coordinate(transform.get('y', 0)),
        'scale': max(0.1, min(10, float(transform.get('scale', 1)) if transform.get('scale') else 1))
    }


def validate_uuid(value: Any) -> Optional[str]:
    """Validate UUID format."""
    if not isinstance(value, str):
        return None
    if UUID_PATTERN.match(value):
        return value.lower()
    return None


def validate_user_name(name: Any) -> str:
    """Validate and sanitize user name."""
    if not isinstance(name, str):
        return 'Anonymous'
    # Strip, limit length, remove control characters
    clean = ''.join(c for c in name if c.isprintable())
    clean = clean.strip()[:MAX_USER_NAME_LENGTH]
    return clean or 'Anonymous'


def validate_image_data(data: Any) -> Optional[str]:
    """Validate image data URL."""
    if not isinstance(data, str):
        return None
    
    # Check format
    if not DATA_URL_PATTERN.match(data):
        return None
    
    # Check size
    if len(data) > MAX_IMAGE_DATA_SIZE:
        return None
    
    return data


def validate_stroke_ids(ids: Any) -> List[str]:
    """Validate array of stroke IDs."""
    if not isinstance(ids, list):
        return []
    
    validated = []
    for id_val in ids[:MAX_STROKE_IDS_PER_DELETE]:
        valid_id = validate_uuid(id_val)
        if valid_id:
            validated.append(valid_id)
    
    return validated


def validate_stroke_complete(data: Dict) -> Tuple[bool, Dict, str]:
    """
    Validate stroke-complete event data.
    Returns: (is_valid, sanitized_data, error_message)
    """
    errors = []
    
    stroke_id = validate_uuid(data.get('strokeId'))
    if not stroke_id:
        errors.append('Invalid strokeId')
    
    points = validate_points(data.get('points', []))
    if len(points) < 2:
        errors.append('Stroke must have at least 2 points')
    
    if errors:
        return False, {}, '; '.join(errors)
    
    return True, {
        'strokeId': stroke_id,
        'points': points,
        'color': validate_color(data.get('color')),
        'strokeWidth': validate_stroke_width(data.get('strokeWidth')),
        'transform': validate_transform(data.get('transform'))
    }, ''


def validate_image_add(data: Dict) -> Tuple[bool, Dict, str]:
    """Validate image-add event data."""
    errors = []
    
    image_id = validate_uuid(data.get('imageId'))
    if not image_id:
        errors.append('Invalid imageId')
    
    image_data = validate_image_data(data.get('data'))
    if not image_data:
        errors.append('Invalid or missing image data')
    
    if errors:
        return False, {}, '; '.join(errors)
    
    return True, {
        'imageId': image_id,
        'data': image_data,
        'x': validate_coordinate(data.get('x', 0)),
        'y': validate_coordinate(data.get('y', 0)),
        'width': max(10, min(5000, float(data.get('width', 200)) if data.get('width') else 200)),
        'height': max(10, min(5000, float(data.get('height', 200)) if data.get('height') else 200)),
        'transform': validate_transform(data.get('transform'))
    }, ''
```

---

### 1.3 WebSocket Rate Limiting

**Problem:** No rate limiting on WebSocket events - DoS vulnerability.

**Solution:** Implement per-connection rate limiting.

**Add to `server.py`:**

```python
import time
from collections import defaultdict

# Rate limiting for WebSocket events
class SocketRateLimiter:
    def __init__(self):
        self.events = defaultdict(lambda: {'count': 0, 'reset_time': time.time()})
        self.limits = {
            'stroke-point': (200, 1),      # 200 per second (for smooth drawing)
            'stroke-complete': (30, 1),    # 30 per second
            'cursor-move': (30, 1),        # 30 per second
            'image-add': (5, 60),          # 5 per minute
            'clear': (2, 60),              # 2 per minute
            'default': (60, 1)             # 60 per second default
        }
    
    def is_allowed(self, sid: str, event: str) -> bool:
        """Check if event is allowed under rate limit."""
        limit, window = self.limits.get(event, self.limits['default'])
        key = f"{sid}:{event}"
        now = time.time()
        
        entry = self.events[key]
        if now > entry['reset_time'] + window:
            entry['count'] = 0
            entry['reset_time'] = now
        
        entry['count'] += 1
        return entry['count'] <= limit
    
    def cleanup_old_entries(self):
        """Remove stale entries (call periodically)."""
        now = time.time()
        stale = [k for k, v in self.events.items() if now > v['reset_time'] + 300]
        for k in stale:
            del self.events[k]


rate_limiter = SocketRateLimiter()


def rate_limit_check(event: str) -> bool:
    """Check rate limit and emit error if exceeded."""
    if not rate_limiter.is_allowed(request.sid, event):
        emit('error', {'message': 'Rate limit exceeded', 'event': event})
        return False
    return True
```

**Usage in handlers:**

```python
@socketio.on('stroke-point')
def handle_stroke_point(data):
    if not rate_limit_check('stroke-point'):
        return
    # ... rest of handler
```

---

### 1.4 Production Secret Enforcement

**Problem:** Default insecure secrets used if env vars not set.

**Solution:** Fail fast if secrets not configured.

**Add to `server.py` (after app initialization):**

```python
# Production security checks
def check_production_config():
    """Ensure production configuration is secure."""
    is_production = os.environ.get('FLASK_ENV') == 'production' or \
                   os.environ.get('ENVIRONMENT') == 'production'
    
    if is_production:
        secret_key = os.environ.get('SECRET_KEY', '')
        if not secret_key or secret_key == 'dev-secret-key-change-in-production':
            raise RuntimeError("SECRET_KEY must be set to a secure value in production!")
        
        admin_token = os.environ.get('ADMIN_API_TOKEN', '')
        if not admin_token or admin_token == 'dev-admin-token-change-in-production':
            raise RuntimeError("ADMIN_API_TOKEN must be set to a secure value in production!")
        
        if app.debug:
            raise RuntimeError("Debug mode must be disabled in production!")


# Call at startup
if __name__ == '__main__':
    check_production_config()
    init_db()
    # ...
```

---

### 1.5 CORS Restriction

**Problem:** CORS allows any origin (`*`).

**Solution:** Restrict to specific origins.

**Update `server.py`:**

```python
# Get allowed origins from environment
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '*').split(',')

socketio = SocketIO(
    app, 
    cors_allowed_origins=ALLOWED_ORIGINS if ALLOWED_ORIGINS != ['*'] else "*",
    async_mode='eventlet'
)
```

**In production, set:**
```bash
export ALLOWED_ORIGINS="https://yourdomain.com,https://www.yourdomain.com"
```

---

## Phase 2: High Priority Fixes
**Timeline: 2-3 days**

### 2.1 Remove Token from API Responses

**Problem:** Access token exposed in `/get/<token>` response.

**File:** `server.py`

```python
@app.route('/get/<token>')
@limiter.limit("30 per minute")
def get_document(token):
    """Get document data for rendering whiteboard."""
    doc = get_document_by_token(token)
    
    if not doc:
        abort(404)

    # Return sanitized data without access_token
    result = doc.to_dict()
    result.pop('access_token', None)
    result.pop('id', None)  # Don't expose internal ID either
    return result
```

---

### 2.2 Board Content Limits

**Problem:** No limits on strokes/images per board - memory exhaustion.

**Add validation in handlers:**

```python
@socketio.on('stroke-complete')
def handle_stroke_complete(data):
    # ... authentication and validation ...
    
    # Check board limits
    stroke_count = Stroke.select().where(Stroke.document_id == doc_id).count()
    if stroke_count >= MAX_STROKES_PER_BOARD:
        emit('error', {'message': 'Board stroke limit reached'})
        return
    
    # ... rest of handler


@socketio.on('image-add')
def handle_image_add(data):
    # ... authentication and validation ...
    
    # Check board limits
    image_count = Image.select().where(Image.document_id == doc_id).count()
    if image_count >= MAX_IMAGES_PER_BOARD:
        emit('error', {'message': 'Board image limit reached'})
        return
    
    # ... rest of handler
```

---

### 2.3 Database Migration to PostgreSQL

**Problem:** SQLite not suitable for 300 concurrent users.

**Solution:** Use PostgreSQL via DATABASE_URL environment variable.

**File:** `models.py` (already supports this, just needs to be enabled)

**Production setup:**
```bash
# Install PostgreSQL adapter
pip install psycopg2-binary

# Set environment variable
export DATABASE_URL="postgresql://user:password@localhost:5432/whiteboard"
```

**Add connection pooling:**

```python
# In models.py
if DATABASE_URL and DATABASE_URL.startswith('postgres'):
    from playhouse.pool import PooledPostgresqlExtDatabase
    from playhouse.db_url import parse
    
    parsed = parse(DATABASE_URL)
    db = PooledPostgresqlExtDatabase(
        parsed['database'],
        max_connections=20,
        stale_timeout=300,
        user=parsed['user'],
        password=parsed['password'],
        host=parsed['host'],
        port=parsed['port']
    )
```

---

## Phase 3: Medium Priority Fixes
**Timeline: 1-2 days**

### 3.1 Security Headers

**Add to `server.py`:**

```python
@app.after_request
def add_security_headers(response):
    """Add security headers to all responses."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # CSP - adjust as needed
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://cdn.socket.io https://esm.sh; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' ws: wss:; "
        "font-src 'self';"
    )
    
    return response
```

---

### 3.2 Logging and Monitoring

**Add structured logging:**

```python
import logging
from logging.handlers import RotatingFileHandler

def setup_logging():
    """Configure production logging."""
    # Create logs directory
    os.makedirs('logs', exist_ok=True)
    
    # File handler with rotation
    file_handler = RotatingFileHandler(
        'logs/whiteboard.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s] %(message)s'
    ))
    file_handler.setLevel(logging.INFO)
    
    # Security events logger
    security_handler = RotatingFileHandler(
        'logs/security.log',
        maxBytes=10*1024*1024,
        backupCount=10
    )
    security_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s %(message)s'
    ))
    security_handler.setLevel(logging.WARNING)
    
    app.logger.addHandler(file_handler)
    
    # Security logger for rate limits, validation failures, etc.
    security_logger = logging.getLogger('security')
    security_logger.addHandler(security_handler)
    security_logger.setLevel(logging.WARNING)
    
    return security_logger


security_logger = setup_logging()


# Usage in rate limiter:
def rate_limit_check(event: str) -> bool:
    if not rate_limiter.is_allowed(request.sid, event):
        security_logger.warning(
            f"Rate limit exceeded: sid={request.sid}, event={event}, ip={request.remote_addr}"
        )
        emit('error', {'message': 'Rate limit exceeded'})
        return False
    return True
```

---

### 3.3 User Name Sanitization on Display

**Update `templates/index.html`** - Already uses `x-text` which is safe, but add extra protection:

```javascript
// In whiteboardApp()
setUserName() {
    let name = this.userNameInput.trim();
    if (!name) return;
    
    // Sanitize: remove any HTML-like content
    name = name.replace(/[<>]/g, '');
    name = name.substring(0, 50);
    
    this.userName = name;
    // ... rest
}
```

---

## Phase 4: Infrastructure Recommendations
**For DevOps / Deployment**

### 4.1 Environment Variables Checklist

```bash
# Required for production
SECRET_KEY=<random-64-char-string>
ADMIN_API_TOKEN=<random-32-char-string>
DATABASE_URL=postgresql://user:pass@host:5432/dbname
FLASK_ENV=production
ALLOWED_ORIGINS=https://yourdomain.com

# Optional
MAX_STROKES_PER_BOARD=10000
MAX_IMAGES_PER_BOARD=100
MAX_IMAGE_SIZE_MB=5
```

### 4.2 Reverse Proxy Configuration (Nginx)

Use traefik for reverse proxy without SSL.

When actually deploying put this whole app behind another reverse proxy that handles SSL termination (e.g. Nginx, Traefik, Caddy).


### 4.3 Docker Security

```dockerfile
FROM python:3.11-slim

# Non-root user
RUN useradd -m -u 1000 appuser
USER appuser

WORKDIR /app

# Copy only requirements first (caching)
COPY --chown=appuser:appuser requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

# Don't run as root
EXPOSE 5050

CMD ["gunicorn", "-k", "eventlet", "-w", "1", "-b", "0.0.0.0:5050", "server:app"]
```

---

## Implementation Checklist

### Phase 1 (Critical) - Days 1-5
- [ ] Implement server-side session management
- [ ] Create `validators.py` with all validation functions
- [ ] Apply validation to all SocketIO handlers
- [ ] Implement WebSocket rate limiting
- [ ] Add production secret checks
- [ ] Restrict CORS origins

### Phase 2 (High) - Days 6-8
- [ ] Remove sensitive data from API responses
- [ ] Implement board content limits
- [ ] Set up PostgreSQL database
- [ ] Configure connection pooling

### Phase 3 (Medium) - Days 9-10
- [ ] Add security headers
- [ ] Implement structured logging
- [ ] Add security event logging
- [ ] Sanitize user input on client side

### Phase 4 (Infrastructure) - Days 11-12
- [ ] Set up environment variables
- [ ] Configure reverse proxy
- [ ] Set up Docker with non-root user
- [ ] Create deployment documentation

---

## Testing Checklist

After implementing fixes, verify:

1. **Session Isolation Test**
   - Connect two clients to different boards
   - Try to send events with the other board's token
   - Verify events are blocked

2. **Input Validation Test**
   - Send malformed stroke data (invalid UUIDs, excessive points)
   - Send invalid color values
   - Send oversized images
   - Verify all are rejected

3. **Rate Limit Test**
   - Send rapid-fire events
   - Verify rate limiting kicks in
   - Verify other users aren't affected

4. **Load Test**
   - Simulate 300 concurrent users
   - Monitor memory usage
   - Monitor database connection pool
   - Verify response times

---

## Summary Timeline

| Phase | Priority | Days | Status |
|-------|----------|------|--------|
| Phase 1 | Critical | 5 | ✅ Done |
| Phase 2 | High | 3 | ✅ Done |
| Phase 3 | Medium | 2 | ✅ Done |
| Phase 4 | Infrastructure | 2 | ✅ Done |
| **Total** | | **12** | ✅ **Complete** |

---

**Document prepared by:** Security Analysis Team  
**Completed:** January 10, 2026
