#!/usr/bin/env python
"""Simple script to run the server without debug mode for testing."""
from server import app, socketio, init_db

if __name__ == '__main__':
    init_db()
    print("Starting whiteboard server on http://localhost:5050")
    socketio.run(app, host='0.0.0.0', port=5050, debug=False, use_reloader=False)
