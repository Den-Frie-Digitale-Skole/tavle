"""
Main Flask application with SocketIO for real-time collaboration.
Security-hardened version with input validation, session management, and rate limiting.
"""
import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, abort, jsonify, redirect, url_for
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from models import init_db, get_document_by_token, open_db_connection, close_db_connection, get_pool_status
from api import api_bp
from socketio_handlers import register_socketio_handlers
from setup import needs_setup, complete_setup, get_admin_token, get_secret_key, get_or_create_admin_token, mark_setup_complete
from docs import docs_bp

# =============================================================================
# Logging Setup
# =============================================================================

def setup_logging(app_instance):
    """
    Configure production logging with file rotation.
    Creates separate logs for application and security events.
    """
    # Create logs directory
    log_dir = os.environ.get('LOG_DIR', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # Determine log level from environment
    log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO)
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s %(levelname)s [%(name)s] %(message)s'
    )
    
    # Application log with rotation (10MB, 5 backups)
    app_handler = RotatingFileHandler(
        os.path.join(log_dir, 'whiteboard.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    app_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s] %(message)s'
    ))
    app_handler.setLevel(log_level)
    app_instance.logger.addHandler(app_handler)
    
    # Security log with rotation (10MB, 10 backups - keep more history)
    security_handler = RotatingFileHandler(
        os.path.join(log_dir, 'security.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10
    )
    security_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s] %(message)s'
    ))
    security_handler.setLevel(logging.WARNING)
    
    # Create security logger
    security_logger = logging.getLogger('security')
    security_logger.addHandler(security_handler)
    security_logger.setLevel(logging.WARNING)
    
    # Also add console handler for security events in production
    if os.environ.get('FLASK_ENV') == 'production':
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s SECURITY %(levelname)s %(message)s'
        ))
        security_logger.addHandler(console_handler)
    
    return security_logger


logger = logging.getLogger(__name__)

# =============================================================================
# Initialize Flask app
# =============================================================================

app = Flask(__name__)
app.config['SECRET_KEY'] = get_secret_key()

# Setup logging (creates security_logger as module-level for import by other modules)
security_logger = setup_logging(app)

# =============================================================================
# Production Security Checks
# =============================================================================

def check_production_config():
    """Ensure production configuration is secure."""
    is_production = (
        os.environ.get('FLASK_ENV') == 'production' or
        os.environ.get('ENVIRONMENT') == 'production'
    )
    
    if is_production:
        secret_key = os.environ.get('SECRET_KEY', '')
        if not secret_key or secret_key == 'dev-secret-key-change-in-production':
            raise RuntimeError("SECRET_KEY must be set to a secure value in production!")
        
        admin_token = os.environ.get('ADMIN_API_TOKEN', '')
        if not admin_token or admin_token == 'dev-admin-token-change-in-production':
            raise RuntimeError("ADMIN_API_TOKEN must be set to a secure value in production!")
        
        if app.debug:
            logger.warning("Debug mode is enabled - should be disabled in production!")

# =============================================================================
# Initialize rate limiter (HTTP routes)
# =============================================================================

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"], 
    storage_uri="memory://",
)

# =============================================================================
# Initialize SocketIO with CORS restriction
# =============================================================================

# Get allowed origins from environment (comma-separated), default to * for dev
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '*')
if ALLOWED_ORIGINS != '*':
    ALLOWED_ORIGINS = [origin.strip() for origin in ALLOWED_ORIGINS.split(',')]

socketio = SocketIO(
    app,
    cors_allowed_origins=ALLOWED_ORIGINS,
    async_mode='eventlet',
    ping_timeout=60,
    ping_interval=25
)

# Register all SocketIO event handlers
register_socketio_handlers(socketio)

# =============================================================================
# Security Headers
# =============================================================================

# Content Security Policy - now using local vendor files, much stricter CSP possible
CSP_POLICY = os.environ.get('CSP_POLICY', (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "  # 'unsafe-eval' needed for some libs, consider removing if possible
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: blob:; "
    "connect-src 'self' ws: wss:; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "frame-ancestors 'self';"
))


@app.after_request
def add_security_headers(response):
    """Add security headers to all responses."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = CSP_POLICY
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    return response

# =============================================================================
# Database Connection Management (for connection pooling)
# =============================================================================

@app.before_request
def before_request():
    """Open database connection before each request."""
    open_db_connection()


@app.teardown_request
def teardown_request(exception=None):
    """Close database connection after each request (returns to pool)."""
    close_db_connection()

# =============================================================================
# Error Handlers
# =============================================================================

@app.errorhandler(400)
def bad_request_error(error):
    """Handle 400 Bad Request errors."""
    return render_template('errors/400.html'), 400


@app.errorhandler(403)
def forbidden_error(error):
    """Handle 403 Forbidden errors."""
    return render_template('errors/403.html'), 403


@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 Not Found errors."""
    return render_template('errors/404.html'), 404


@app.errorhandler(429)
def too_many_requests_error(error):
    """Handle 429 Too Many Requests errors (rate limiting)."""
    return render_template('errors/429.html'), 429


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 Internal Server errors."""
    logger.error(f'Internal server error: {error}')
    return render_template('errors/500.html'), 500

# =============================================================================
# Register API blueprint
# =============================================================================

app.register_blueprint(api_bp)

# =============================================================================
# Public Routes
# =============================================================================

@app.route('/setup')
@limiter.limit("10 per minute")
def setup_page():
    """
    First-run setup page.
    Only accessible if setup hasn't been completed yet.
    Shows the generated admin API token.
    """
    if not needs_setup():
        # Setup already complete, redirect to landing
        return redirect(url_for('index'))
    
    # Get or generate the admin token (but don't mark setup as complete)
    admin_token = get_or_create_admin_token()
    
    return render_template('setup.html', 
                           admin_token=admin_token,
                           setup_complete=False)


@app.route('/setup/complete', methods=['POST'])
@limiter.limit("5 per minute")
def complete_setup_route():
    """
    Mark setup as complete when user confirms they've saved their token.
    """
    if not needs_setup():
        # Already complete
        return redirect(url_for('index'))
    
    mark_setup_complete()
    return redirect(url_for('index'))


@app.route('/')
@limiter.limit("30 per minute")
def index():
    """Landing page. Redirects to setup if first run."""
    if needs_setup():
        return redirect(url_for('setup_page'))
    return render_template('landing.html')


@app.route('/docs')
@limiter.limit("30 per minute")
def api_docs():
    """API Documentation page."""
    return render_template('docs.html')


@app.route('/board/<token>')
@app.route('/b/<token>')
@limiter.limit("30 per minute")
def board(token):
    """Render whiteboard for a specific document using access token."""
    doc = get_document_by_token(token)
    if not doc:
        abort(403)
    return render_template('index.html', token_id=token, access_token=token)


@app.route('/get/<token>')
@limiter.limit("30 per minute")
def get_document(token):
    """Get document data for rendering whiteboard (without exposing sensitive data)."""
    doc = get_document_by_token(token)
    
    if not doc:
        logger.info(f'Document not found for token: {token[:10]}...')
        abort(404)

    # Return sanitized data - remove sensitive fields
    result = doc.to_dict()
    result.pop('access_token', None)  # Don't expose token in response
    result.pop('id', None)  # Don't expose internal ID
    return result


@app.route('/health')
@limiter.exempt
def health_check():
    """
    Health check endpoint for monitoring.
    Returns database pool status in production.
    """
    pool_status = get_pool_status()
    
    return jsonify({
        'status': 'healthy',
        'database': 'postgresql' if pool_status else 'sqlite',
        'pool': pool_status,
    })


app.register_blueprint(docs_bp)

# =============================================================================
# Application Entry Point
# =============================================================================

if __name__ == '__main__':
    # Check production configuration
    check_production_config()
    
    # Initialize database
    init_db()
    
    # Log startup
    logger.info('Starting whiteboard server on http://localhost:5050')
    logger.info(f'CORS allowed origins: {ALLOWED_ORIGINS}')
    
    # Run with SocketIO
    socketio.run(app, host='0.0.0.0', port=5050, debug=True)
