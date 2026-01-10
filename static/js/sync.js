/**
 * SyncManager Class
 * Handles all real-time synchronization via Socket.IO.
 * Connects the Whiteboard to the server and manages event flow.
 */
class SyncManager {
    constructor(whiteboard, documentId, options = {}) {
        this.whiteboard = whiteboard;
        this.documentId = documentId;
        this.socket = null;
        this.connected = false;

        // Throttling
        this.throttleInterval = options.throttleInterval || 16;  // ~60fps
        this.lastEmitTime = 0;
        this.pendingPoint = null;
        this.throttleTimer = null;

        // Server URL
        this.serverUrl = options.serverUrl || window.location.origin;

        // Bind whiteboard callbacks
        this._bindWhiteboardCallbacks();
    }

    // =========================================================================
    // Connection Management
    // =========================================================================

    connect() {
        return new Promise((resolve, reject) => {
            try {
                this.socket = io(this.serverUrl, {
                    transports: ['websocket', 'polling']
                });

                this.socket.on('connect', () => {
                    console.log('Socket connected');
                    this.connected = true;
                    this.joinRoom();
                    resolve();
                });

                this.socket.on('disconnect', () => {
                    console.log('Socket disconnected');
                    this.connected = false;
                });

                this.socket.on('connect_error', (error) => {
                    console.error('Socket connection error:', error);
                    reject(error);
                });

                // Bind inbound event handlers
                this._bindSocketEvents();

            } catch (error) {
                reject(error);
            }
        });
    }

    disconnect() {
        if (this.socket) {
            this.socket.emit('leave', { documentId: this.documentId });
            this.socket.disconnect();
            this.socket = null;
            this.connected = false;
        }
    }

    joinRoom() {
        if (this.socket && this.connected) {
            this.socket.emit('join', { documentId: this.documentId });
        }
    }

    // =========================================================================
    // Whiteboard Callbacks
    // =========================================================================

    _bindWhiteboardCallbacks() {
        // Stroke point (throttled)
        this.whiteboard.onStrokePoint = (data) => {
            this._emitThrottled('stroke-point', {
                documentId: this.documentId,
                ...data
            });
        };

        // Stroke complete
        this.whiteboard.onStrokeComplete = (data) => {
            // Flush any pending throttled point first
            this._flushThrottled();

            this._emit('stroke-complete', {
                documentId: this.documentId,
                ...data
            });
        };

        // Stroke update (move/transform)
        this.whiteboard.onStrokeUpdate = (data) => {
            this._emit('stroke-update', {
                documentId: this.documentId,
                ...data
            });
        };

        // Stroke delete
        this.whiteboard.onStrokeDelete = (data) => {
            this._emit('stroke-delete', {
                documentId: this.documentId,
                ...data
            });
        };

        // Clear canvas
        this.whiteboard.onClear = () => {
            this._emit('clear', {
                documentId: this.documentId
            });
        };

        // Image add
        this.whiteboard.onImageAdd = (data) => {
            this._emit('image-add', {
                documentId: this.documentId,
                imageId: data.id,
                data: data.data,
                x: data.x,
                y: data.y,
                width: data.width,
                height: data.height,
                transform: data.transform
            });
        };

        // Image update (move/transform)
        this.whiteboard.onImageUpdate = (data) => {
            this._emit('image-update', {
                documentId: this.documentId,
                ...data
            });
        };

        // Image delete
        this.whiteboard.onImageDelete = (data) => {
            this._emit('image-delete', {
                documentId: this.documentId,
                ...data
            });
        };
    }

    // =========================================================================
    // Socket Event Handlers (Inbound)
    // =========================================================================

    _bindSocketEvents() {
        // Joined room confirmation
        this.socket.on('joined', (data) => {
            console.log('Joined room:', data.documentId);
        });

        // Remote stroke point
        this.socket.on('remote-stroke-point', (data) => {
            this.whiteboard.applyRemoteStrokePoint(data);
        });

        // Remote stroke complete
        this.socket.on('remote-stroke-complete', (data) => {
            this.whiteboard.applyRemoteStrokeComplete(data);
        });

        // Remote stroke update
        this.socket.on('remote-stroke-update', (data) => {
            this.whiteboard.applyRemoteStrokeUpdate(data);
        });

        // Remote stroke delete
        this.socket.on('remote-stroke-delete', (data) => {
            this.whiteboard.applyRemoteStrokeDelete(data);
        });

        // Remote clear
        this.socket.on('remote-clear', (data) => {
            this.whiteboard.applyRemoteClear();
        });

        // Remote image add
        this.socket.on('remote-image-add', (data) => {
            this.whiteboard.applyRemoteImageAdd(data);
        });

        // Remote image update
        this.socket.on('remote-image-update', (data) => {
            this.whiteboard.applyRemoteImageUpdate(data);
        });

        // Remote image delete
        this.socket.on('remote-image-delete', (data) => {
            this.whiteboard.applyRemoteImageDelete(data);
        });
    }

    // =========================================================================
    // Emission Helpers
    // =========================================================================

    _emit(event, data) {
        if (this.socket && this.connected) {
            this.socket.emit(event, data);
        }
    }

    _emitThrottled(event, data) {
        const now = Date.now();

        if (now - this.lastEmitTime >= this.throttleInterval) {
            // Enough time has passed, emit immediately
            this._emit(event, data);
            this.lastEmitTime = now;
            this.pendingPoint = null;
        } else {
            // Store for later emission
            this.pendingPoint = { event, data };

            // Set up timer if not already set
            if (!this.throttleTimer) {
                const delay = this.throttleInterval - (now - this.lastEmitTime);
                this.throttleTimer = setTimeout(() => {
                    this._flushThrottled();
                }, delay);
            }
        }
    }

    _flushThrottled() {
        if (this.throttleTimer) {
            clearTimeout(this.throttleTimer);
            this.throttleTimer = null;
        }

        if (this.pendingPoint) {
            this._emit(this.pendingPoint.event, this.pendingPoint.data);
            this.pendingPoint = null;
            this.lastEmitTime = Date.now();
        }
    }

    // =========================================================================
    // Document Persistence
    // =========================================================================

    async loadDocument() {
        try {
            const response = await fetch(`/api/docs/${this.documentId}`);

            if (!response.ok) {
                throw new Error(`Failed to load document: ${response.status}`);
            }

            const data = await response.json();

            // Import strokes to whiteboard
            if (data.strokes && Array.isArray(data.strokes)) {
                const strokes = data.strokes.map(s => ({
                    id: s.id,
                    points: s.points,
                    color: s.color,
                    strokeWidth: s.strokeWidth,
                    transform: s.transform || { x: 0, y: 0, scale: 1 }
                }));
                this.whiteboard.importStrokes(strokes);
            }

            // Import images to whiteboard
            if (data.images && Array.isArray(data.images)) {
                const images = data.images.map(img => ({
                    id: img.id,
                    data: img.data,
                    x: img.x,
                    y: img.y,
                    width: img.width,
                    height: img.height,
                    transform: img.transform || { x: 0, y: 0, scale: 1 }
                }));
                this.whiteboard.importImages(images);
            }

            return data;
        } catch (error) {
            console.error('Error loading document:', error);
            throw error;
        }
    }

    async saveStroke(stroke) {
        try {
            const response = await fetch(`/api/docs/${this.documentId}/strokes`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    id: stroke.id,
                    points: stroke.points,
                    color: stroke.color,
                    strokeWidth: stroke.strokeWidth,
                    transform: stroke.transform
                })
            });

            if (!response.ok) {
                throw new Error(`Failed to save stroke: ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error('Error saving stroke:', error);
            throw error;
        }
    }

    async deleteStrokes(strokeIds) {
        try {
            const promises = strokeIds.map(id =>
                fetch(`/api/docs/${this.documentId}/strokes/${id}`, {
                    method: 'DELETE'
                })
            );

            await Promise.all(promises);
        } catch (error) {
            console.error('Error deleting strokes:', error);
            throw error;
        }
    }

    async clearDocument() {
        try {
            const response = await fetch(`/api/docs/${this.documentId}/strokes`, {
                method: 'DELETE'
            });

            if (!response.ok) {
                throw new Error(`Failed to clear document: ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error('Error clearing document:', error);
            throw error;
        }
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SyncManager;
}
