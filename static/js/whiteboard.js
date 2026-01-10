/**
 * Whiteboard Class
 * Self-contained drawing canvas with Perfect-Freehand integration.
 * Handles drawing, selection, zoom, pan, and stroke manipulation.
 */
class Whiteboard {
    constructor(baseCanvas, activeCanvas, options = {}) {
        // Canvas elements
        this.baseCanvas = baseCanvas;
        this.activeCanvas = activeCanvas;
        this.baseCtx = baseCanvas.getContext('2d');
        this.activeCtx = activeCanvas.getContext('2d');

        // Stroke storage
        this.strokes = new Map();  // strokeId -> stroke data
        this.selectedStrokes = new Set();  // Multi-select support
        this.currentStroke = null;
        this.currentStrokeId = null;

        // Image storage
        this.images = new Map();  // imageId -> image data
        this.selectedImages = new Set();  // Multi-select support for images
        this.imageCache = new Map();  // imageId -> HTMLImageElement (loaded images)

        // Z-index counter for layering (strokes and images share the same z-space)
        this.nextZIndex = 0;

        // Drawing settings
        this.color = options.color || '#000000';
        this.strokeWidth = options.strokeWidth || 4.0;

        // Canvas settings
        this.backgroundColor = options.backgroundColor || '#ffffff';
        this.showGrid = options.showGrid !== undefined ? options.showGrid : true;

        // View transform
        this.zoom = 1;
        this.pan = { x: 0, y: 0 };
        this.minZoom = 0.1;
        this.maxZoom = 5;

        // Interaction mode
        this.mode = 'draw';  // 'draw' | 'select' | 'pan' | 'erase'
        this.isDrawing = false;
        this.isPanning = false;
        this.isMoving = false;
        this.isResizing = false;
        this.isErasing = false;
        this.eraserWidth = 20;  // Eraser radius
        this.resizeHandle = null;  // 'nw' | 'ne' | 'sw' | 'se' | null
        this.resizeImageId = null;
        this.resizeStartBounds = null;
        this.lastPointer = { x: 0, y: 0 };
        this.dragStart = { x: 0, y: 0 };

        // Remote strokes being drawn (ghost lines)
        this.remoteStrokes = new Map();  // strokeId -> partial stroke

        // Callbacks for sync
        this.onStrokePoint = null;
        this.onStrokeComplete = null;
        this.onStrokeUpdate = null;
        this.onStrokeDelete = null;
        this.onClear = null;
        this.onImageAdd = null;
        this.onImageUpdate = null;
        this.onImageDelete = null;
        this.onCursorMove = null;  // Cursor position broadcast

        // Remote users and cursors
        this.remoteUsers = new Map();  // oduserId -> { name, color, cursor: {x, y}, lastSeen }
        this.localUserId = null;
        this.localUserName = null;
        this.localUserColor = null;
        this.cursorColors = [
            '#e74c3c', '#3498db', '#2ecc71', '#9b59b6', 
            '#f39c12', '#1abc9c', '#e91e63', '#00bcd4'
        ];

        // History for undo/redo
        this.history = [];  // Array of action objects
        this.historyIndex = -1;  // Current position in history
        this.maxHistorySize = 50;  // Limit history size

        // Perfect-Freehand options - tuned for smooth drawing
        this.freehandOptions = {
            size: this.strokeWidth,
            thinning: 0.6,
            smoothing: 0.8,
            streamline: 0.7,
            easing: (t) => t,
            simulatePressure: true,
            last: true,
            start: {
                cap: true,
                taper: 0,
                easing: (t) => t
            },
            end: {
                cap: true,
                taper: 0,
                easing: (t) => t
            }
        };

        // Bind event handlers
        this._bindEvents();

        // Initial setup
        this.resize();
    }

    // =========================================================================
    // Event Binding
    // =========================================================================

    _bindEvents() {
        // Drawing events on active canvas
        this.activeCanvas.addEventListener('pointerdown', this._onPointerDown.bind(this));
        this.activeCanvas.addEventListener('pointermove', this._onPointerMove.bind(this));
        this.activeCanvas.addEventListener('pointerup', this._onPointerUp.bind(this));
        this.activeCanvas.addEventListener('pointerleave', this._onPointerUp.bind(this));

        // Zoom with mouse wheel
        this.activeCanvas.addEventListener('wheel', this._onWheel.bind(this), { passive: false });

        // Keyboard shortcuts
        document.addEventListener('keydown', this._onKeyDown.bind(this));
        document.addEventListener('keyup', this._onKeyUp.bind(this));

        // Paste event for images
        document.addEventListener('paste', this._onPaste.bind(this));

        // Window resize
        window.addEventListener('resize', this.resize.bind(this));
    }

    _onPaste(e) {
        const items = e.clipboardData?.items;
        if (!items) return;

        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault();
                const file = item.getAsFile();
                this._handleImageFile(file);
                break;
            }
        }
    }

    _handleImageFile(file, x = null, y = null) {
        const reader = new FileReader();
        reader.onload = (event) => {
            const dataUrl = event.target.result;
            
            // Create a temporary image to get dimensions
            const img = new window.Image();
            img.onload = () => {
                // Calculate position (center of viewport if not specified)
                const canvasRect = this.activeCanvas.getBoundingClientRect();
                const centerX = x !== null ? x : (canvasRect.width / 2 - this.pan.x) / this.zoom;
                const centerY = y !== null ? y : (canvasRect.height / 2 - this.pan.y) / this.zoom;
                
                // Scale image to reasonable size (max 400px)
                let width = img.width;
                let height = img.height;
                const maxSize = 400;
                
                if (width > maxSize || height > maxSize) {
                    const ratio = Math.min(maxSize / width, maxSize / height);
                    width *= ratio;
                    height *= ratio;
                }
                
                const imageId = this._generateId('image');
                const imageData = {
                    id: imageId,
                    data: dataUrl,
                    x: centerX - width / 2,
                    y: centerY - height / 2,
                    width: width,
                    height: height,
                    transform: { x: 0, y: 0, scale: 1 },
                    zIndex: this.nextZIndex++
                };
                
                // Add to images map
                this.images.set(imageId, imageData);
                
                // Cache the loaded image
                this.imageCache.set(imageId, img);

                // Add to history
                this._addToHistory({
                    type: 'image-add',
                    imageId: imageId,
                    image: { ...imageData }
                });
                
                // Redraw
                this._redrawBase();
                
                // Emit event
                if (this.onImageAdd) {
                    this.onImageAdd(imageData);
                }
            };
            img.src = dataUrl;
        };
        reader.readAsDataURL(file);
    }

    addImageFromFile(file) {
        this._handleImageFile(file);
    }

    _onPointerDown(e) {
        e.preventDefault();
        const point = this._getCanvasPoint(e);
        this.lastPointer = { x: e.clientX, y: e.clientY };

        if (this.mode === 'pan' || e.button === 1) {
            // Start panning (middle mouse button or pan mode)
            this.isPanning = true;
            this.activeCanvas.style.cursor = 'grabbing';
            this.isDrawing = false;
            return;
        }

        if (this.mode === 'select') {
            // First check if clicking on a resize handle of a selected image
            const resizeHit = this._hitTestResizeHandle(point.x, point.y);
            if (resizeHit) {
                this.isResizing = true;
                this.resizeHandle = resizeHit.handle;
                this.resizeImageId = resizeHit.imageId;
                const image = this.images.get(resizeHit.imageId);
                this.resizeStartBounds = {
                    x: image.x + (image.transform?.x || 0),
                    y: image.y + (image.transform?.y || 0),
                    width: image.width * (image.transform?.scale || 1),
                    height: image.height * (image.transform?.scale || 1)
                };
                // Save original state for history
                this._resizeStartImageState = {
                    x: image.x,
                    y: image.y,
                    width: image.width,
                    height: image.height,
                    transform: { ...image.transform }
                };
                this.dragStart = { ...point };
                this.activeCanvas.style.cursor = this._getResizeCursor(resizeHit.handle);
                return;
            }

            // Check if clicking on an image first (images are on top)
            const hitImage = this._hitTestImage(point.x, point.y);
            
            if (hitImage) {
                if (e.shiftKey) {
                    // Multi-select toggle
                    if (this.selectedImages.has(hitImage)) {
                        this.selectedImages.delete(hitImage);
                    } else {
                        this.selectedImages.add(hitImage);
                    }
                } else {
                    if (!this.selectedImages.has(hitImage)) {
                        // Single select - clear all selections
                        this.selectedStrokes.clear();
                        this.selectedImages.clear();
                        this.selectedImages.add(hitImage);
                    }
                    // Start moving - save original state for history
                    this.isMoving = true;
                    this.isMovingImages = true;
                    this.dragStart = { ...point };
                    this._moveStartImageStates = new Map();
                    this.selectedImages.forEach(imageId => {
                        const image = this.images.get(imageId);
                        if (image) {
                            this._moveStartImageStates.set(imageId, {
                                x: image.x,
                                y: image.y,
                                width: image.width,
                                height: image.height,
                                transform: { ...image.transform }
                            });
                        }
                    });
                }
                this._redrawActive();
                return;
            }
            
            // Check if clicking on a stroke
            const hitStroke = this._hitTest(point.x, point.y);

            if (hitStroke) {
                if (e.shiftKey) {
                    // Multi-select toggle
                    if (this.selectedStrokes.has(hitStroke)) {
                        this.selectedStrokes.delete(hitStroke);
                    } else {
                        this.selectedStrokes.add(hitStroke);
                    }
                } else {
                    if (!this.selectedStrokes.has(hitStroke)) {
                        // Single select - clear all selections
                        this.selectedStrokes.clear();
                        this.selectedImages.clear();
                        this.selectedStrokes.add(hitStroke);
                    }
                    // Start moving - save original transforms for history
                    this.isMoving = true;
                    this.isMovingImages = false;
                    this.dragStart = { ...point };
                    this._moveStartTransforms = new Map();
                    this.selectedStrokes.forEach(strokeId => {
                        const stroke = this.strokes.get(strokeId);
                        if (stroke) {
                            this._moveStartTransforms.set(strokeId, { ...stroke.transform });
                        }
                    });
                }
                this._redrawActive();
            } else {
                // Click on empty space - deselect all
                if (!e.shiftKey) {
                    this.deselectAll();
                }
            }
            return;
        }

        // Eraser mode
        if (this.mode === 'erase') {
            this.isErasing = true;
            this._eraseAtPoint(point);
            return;
        }

        // Start drawing
        this.isDrawing = true;
        this.currentStrokeId = this._generateId();
        this.currentStroke = {
            id: this.currentStrokeId,
            points: [{ x: point.x, y: point.y, pressure: e.pressure || 0.5 }],
            color: this.color,
            strokeWidth: this.strokeWidth,
            transform: { x: 0, y: 0, scale: 1 },
            zIndex: this.nextZIndex++
        };

        // Emit stroke point
        if (this.onStrokePoint) {
            this.onStrokePoint({
                strokeId: this.currentStrokeId,
                point: this.currentStroke.points[0],
                color: this.color,
                strokeWidth: this.strokeWidth
            });
        }
    }

    _onPointerMove(e) {
        e.preventDefault();
        const point = this._getCanvasPoint(e);
        const clientPoint = { x: e.clientX, y: e.clientY };

        // Broadcast cursor position (throttled)
        if (this.onCursorMove) {
            this.onCursorMove({ x: point.x, y: point.y });
        }

        // Draw eraser cursor
        if (this.mode === 'erase') {
            this._redrawActive();
            this._drawEraserCursor(point);
        }

        // Handle erasing
        if (this.isErasing) {
            this._eraseAtPoint(point);
            return;
        }

        if (this.isPanning) {
            const dx = clientPoint.x - this.lastPointer.x;
            const dy = clientPoint.y - this.lastPointer.y;
            this.pan.x += dx;
            this.pan.y += dy;
            this.lastPointer = clientPoint;
            this._redrawBase();
            this._redrawActive();
            return;
        }

        // Handle resizing
        if (this.isResizing && this.resizeImageId) {
            const image = this.images.get(this.resizeImageId);
            if (image) {
                const dx = point.x - this.dragStart.x;
                const dy = point.y - this.dragStart.y;
                const bounds = this.resizeStartBounds;
                const minSize = 20;  // Minimum size in canvas units

                let newX = bounds.x;
                let newY = bounds.y;
                let newWidth = bounds.width;
                let newHeight = bounds.height;

                // Calculate new bounds based on handle being dragged
                switch (this.resizeHandle) {
                    case 'se':  // Bottom-right
                        newWidth = Math.max(minSize, bounds.width + dx);
                        newHeight = Math.max(minSize, bounds.height + dy);
                        break;
                    case 'sw':  // Bottom-left
                        newWidth = Math.max(minSize, bounds.width - dx);
                        newHeight = Math.max(minSize, bounds.height + dy);
                        newX = bounds.x + bounds.width - newWidth;
                        break;
                    case 'ne':  // Top-right
                        newWidth = Math.max(minSize, bounds.width + dx);
                        newHeight = Math.max(minSize, bounds.height - dy);
                        newY = bounds.y + bounds.height - newHeight;
                        break;
                    case 'nw':  // Top-left
                        newWidth = Math.max(minSize, bounds.width - dx);
                        newHeight = Math.max(minSize, bounds.height - dy);
                        newX = bounds.x + bounds.width - newWidth;
                        newY = bounds.y + bounds.height - newHeight;
                        break;
                }

                // Update image properties
                image.x = newX - (image.transform?.x || 0);
                image.y = newY - (image.transform?.y || 0);
                image.width = newWidth / (image.transform?.scale || 1);
                image.height = newHeight / (image.transform?.scale || 1);

                this._redrawBase();
                this._redrawActive();
            }
            return;
        }

        // Update cursor when hovering over resize handles in select mode
        if (this.mode === 'select' && !this.isMoving && !this.isResizing) {
            const resizeHit = this._hitTestResizeHandle(point.x, point.y);
            if (resizeHit) {
                this.activeCanvas.style.cursor = this._getResizeCursor(resizeHit.handle);
            } else {
                this._updateCursor();
            }
        }

        if (this.isMoving && this.isMovingImages && this.selectedImages.size > 0) {
            const dx = point.x - this.dragStart.x;
            const dy = point.y - this.dragStart.y;

            // Update image transforms
            this.selectedImages.forEach(imageId => {
                const image = this.images.get(imageId);
                if (image) {
                    image.transform.x += dx;
                    image.transform.y += dy;
                }
            });

            this.dragStart = { ...point };
            this._redrawBase();
            this._redrawActive();
            return;
        }

        if (this.isMoving && !this.isMovingImages && this.selectedStrokes.size > 0) {
            const dx = point.x - this.dragStart.x;
            const dy = point.y - this.dragStart.y;

            // Update transforms
            this.selectedStrokes.forEach(strokeId => {
                const stroke = this.strokes.get(strokeId);
                if (stroke) {
                    stroke.transform.x += dx;
                    stroke.transform.y += dy;
                }
            });

            this.dragStart = { ...point };
            this._redrawBase();
            this._redrawActive();
            return;
        }

        if (this.isDrawing && this.currentStroke) {
            const lastPoint = this.currentStroke.points[this.currentStroke.points.length - 1];
            const newPoint = {
                x: point.x,
                y: point.y,
                pressure: e.pressure || 0.5
            };
            
            // Interpolate points if the distance is too large for smooth curves
            if (lastPoint) {
                const dx = newPoint.x - lastPoint.x;
                const dy = newPoint.y - lastPoint.y;
                const distance = Math.sqrt(dx * dx + dy * dy);
                
                // Add intermediate points for smoother curves
                const minDistance = 2; // Minimum distance between points
                if (distance > minDistance) {
                    const steps = Math.ceil(distance / minDistance);
                    for (let i = 1; i < steps; i++) {
                        const t = i / steps;
                        // Smooth interpolation with slight pressure blending
                        const interpPressure = lastPoint.pressure + (newPoint.pressure - lastPoint.pressure) * t;
                        this.currentStroke.points.push({
                            x: lastPoint.x + dx * t,
                            y: lastPoint.y + dy * t,
                            pressure: interpPressure
                        });
                    }
                }
            }
            
            // Add the actual point
            this.currentStroke.points.push(newPoint);

            // Render on active canvas
            this._renderStrokeActive(this.currentStroke);

            // Emit stroke point
            if (this.onStrokePoint) {
                this.onStrokePoint({
                    strokeId: this.currentStrokeId,
                    point: newPoint,
                    color: this.color,
                    strokeWidth: this.strokeWidth
                });
            }
        }
    }

    _onPointerUp(e) {
        if (this.isPanning) {
            this.isPanning = false;
            this._updateCursor();
            return;
        }

        // Handle eraser release
        if (this.isErasing) {
            this.isErasing = false;
            return;
        }

        // Handle resize completion
        if (this.isResizing && this.resizeImageId) {
            const image = this.images.get(this.resizeImageId);
            
            // Add to history
            if (image && this._resizeStartImageState) {
                this._addToHistory({
                    type: 'image-resize',
                    changes: [{
                        imageId: this.resizeImageId,
                        oldState: this._resizeStartImageState,
                        newState: {
                            x: image.x,
                            y: image.y,
                            width: image.width,
                            height: image.height,
                            transform: { ...image.transform }
                        }
                    }]
                });
            }
            this._resizeStartImageState = null;

            if (image && this.onImageUpdate) {
                this.onImageUpdate({
                    imageId: this.resizeImageId,
                    x: image.x,
                    y: image.y,
                    width: image.width,
                    height: image.height,
                    transform: { ...image.transform }
                });
            }
            this.isResizing = false;
            this.resizeHandle = null;
            this.resizeImageId = null;
            this.resizeStartBounds = null;
            this._updateCursor();
            return;
        }

        if (this.isMoving && this.isMovingImages && this.selectedImages.size > 0) {
            // Add to history
            const changes = [];
            this.selectedImages.forEach(imageId => {
                const image = this.images.get(imageId);
                const oldState = this._moveStartImageStates?.get(imageId);
                if (image && oldState) {
                    changes.push({
                        imageId: imageId,
                        oldState: oldState,
                        newState: {
                            x: image.x,
                            y: image.y,
                            width: image.width,
                            height: image.height,
                            transform: { ...image.transform }
                        }
                    });
                }
            });
            if (changes.length > 0) {
                this._addToHistory({ type: 'image-move', changes });
            }
            this._moveStartImageStates = null;

            // Emit image updates
            if (this.onImageUpdate) {
                this.selectedImages.forEach(imageId => {
                    const image = this.images.get(imageId);
                    if (image) {
                        this.onImageUpdate({
                            imageId: imageId,
                            transform: { ...image.transform }
                        });
                    }
                });
            }
            this.isMoving = false;
            this.isMovingImages = false;
            return;
        }

        if (this.isMoving && !this.isMovingImages && this.selectedStrokes.size > 0) {
            // Add to history
            const changes = [];
            this.selectedStrokes.forEach(strokeId => {
                const stroke = this.strokes.get(strokeId);
                const oldTransform = this._moveStartTransforms?.get(strokeId);
                if (stroke && oldTransform) {
                    changes.push({
                        strokeId: strokeId,
                        oldTransform: oldTransform,
                        newTransform: { ...stroke.transform }
                    });
                }
            });
            if (changes.length > 0) {
                this._addToHistory({ type: 'stroke-move', changes });
            }
            this._moveStartTransforms = null;

            // Emit stroke updates
            if (this.onStrokeUpdate) {
                this.selectedStrokes.forEach(strokeId => {
                    const stroke = this.strokes.get(strokeId);
                    if (stroke) {
                        this.onStrokeUpdate({
                            strokeId: strokeId,
                            transform: { ...stroke.transform }
                        });
                    }
                });
            }
            this.isMoving = false;
            return;
        }

        if (this.isDrawing && this.currentStroke) {
            // Complete the stroke
            const completedStroke = { ...this.currentStroke };
            this.strokes.set(this.currentStrokeId, completedStroke);

            // Add to history
            this._addToHistory({
                type: 'stroke-add',
                strokeId: this.currentStrokeId,
                stroke: completedStroke
            });

            // Commit to base canvas
            this._renderStrokeBase(this.currentStroke);

            // Clear active canvas
            this.activeCtx.clearRect(0, 0, this.activeCanvas.width, this.activeCanvas.height);
            this._redrawActive();

            // Emit stroke complete
            if (this.onStrokeComplete) {
                this.onStrokeComplete({
                    strokeId: this.currentStrokeId,
                    points: this.currentStroke.points,
                    color: this.currentStroke.color,
                    strokeWidth: this.currentStroke.strokeWidth,
                    transform: this.currentStroke.transform,
                    zIndex: this.currentStroke.zIndex
                });
            }

            this.currentStroke = null;
            this.currentStrokeId = null;
            this.isDrawing = false;

            // Handle any pending resize that was blocked during drawing
            if (this._pendingResize) {
                this._pendingResize = false;
                this.resize();
            }
        }
    }

    _onWheel(e) {
        e.preventDefault();

        // Don't process while actively drawing - it causes canvas redraw
        if (this.isDrawing) return;

        // Meta/Cmd + scroll = zoom, regular scroll = pan
        if (e.metaKey || e.ctrlKey) {
            // Zoom behavior
            const delta = -e.deltaY * 0.001;
            const newZoom = Math.min(this.maxZoom, Math.max(this.minZoom, this.zoom * (1 + delta)));

            if (newZoom !== this.zoom) {
                // Zoom toward cursor position
                const zoomRatio = newZoom / this.zoom;
                this.pan.x = e.clientX - (e.clientX - this.pan.x) * zoomRatio;
                this.pan.y = e.clientY - (e.clientY - this.pan.y) * zoomRatio;
                this.zoom = newZoom;

                this._redrawBase();
                this._redrawActive();
            }
        } else {
            // Pan/scroll behavior
            this.pan.x -= e.deltaX;
            this.pan.y -= e.deltaY;

            this._redrawBase();
            this._redrawActive();
        }
    }

    _onKeyDown(e) {
        // Space for pan mode
        if (e.code === 'Space' && !this.isDrawing) {
            this.mode = 'pan';
            this._updateCursor();
        }

        // Delete selected strokes/images
        if ((e.code === 'Delete' || e.code === 'Backspace') && (this.selectedStrokes.size > 0 || this.selectedImages.size > 0)) {
            e.preventDefault();
            this.deleteSelected();
        }

        // Undo: Ctrl/Cmd + Z
        if ((e.ctrlKey || e.metaKey) && e.code === 'KeyZ' && !e.shiftKey) {
            e.preventDefault();
            this.undo();
        }

        // Redo: Ctrl/Cmd + Shift + Z or Ctrl/Cmd + Y
        if ((e.ctrlKey || e.metaKey) && ((e.code === 'KeyZ' && e.shiftKey) || e.code === 'KeyY')) {
            e.preventDefault();
            this.redo();
        }

        // Zoom shortcuts
        if (e.ctrlKey || e.metaKey) {
            if (e.code === 'Equal' || e.code === 'NumpadAdd') {
                e.preventDefault();
                this.zoomIn();
            } else if (e.code === 'Minus' || e.code === 'NumpadSubtract') {
                e.preventDefault();
                this.zoomOut();
            } else if (e.code === 'Digit0') {
                e.preventDefault();
                this.resetZoom();
            }
        }

        // Select all
        if ((e.ctrlKey || e.metaKey) && e.code === 'KeyA' && this.mode === 'select') {
            e.preventDefault();
            this.selectAll();
        }
    }

    _onKeyUp(e) {
        if (e.code === 'Space') {
            this.mode = this._previousMode || 'draw';
            this._updateCursor();
        }
    }

    // =========================================================================
    // Coordinate Transforms
    // =========================================================================

    _getCanvasPoint(e) {
        const rect = this.activeCanvas.getBoundingClientRect();
        const x = (e.clientX - rect.left - this.pan.x) / this.zoom;
        const y = (e.clientY - rect.top - this.pan.y) / this.zoom;
        return { x, y };
    }

    _screenToCanvas(x, y) {
        return {
            x: (x - this.pan.x) / this.zoom,
            y: (y - this.pan.y) / this.zoom
        };
    }

    _canvasToScreen(x, y) {
        return {
            x: x * this.zoom + this.pan.x,
            y: y * this.zoom + this.pan.y
        };
    }

    // =========================================================================
    // Eraser
    // =========================================================================

    _eraseAtPoint(point) {
        const eraserRadius = this.eraserWidth / this.zoom;
        const strokesToDelete = [];

        // Find strokes that intersect with the eraser
        this.strokes.forEach((stroke, strokeId) => {
            if (this._strokeIntersectsEraser(stroke, point, eraserRadius)) {
                strokesToDelete.push(strokeId);
            }
        });

        // Delete intersecting strokes
        if (strokesToDelete.length > 0) {
            // Add to history
            const deletedStrokes = strokesToDelete.map(id => {
                const stroke = this.strokes.get(id);
                return { ...stroke };
            });
            
            this._addToHistory({
                type: 'erase',
                strokes: deletedStrokes
            });

            // Delete and notify
            strokesToDelete.forEach(strokeId => {
                this.strokes.delete(strokeId);
                if (this.onStrokeDelete) {
                    this.onStrokeDelete({ strokeId });
                }
            });

            this._redrawBase();
            this._redrawActive();
        }
    }

    _strokeIntersectsEraser(stroke, eraserPoint, eraserRadius) {
        if (!stroke.points || stroke.points.length === 0) return false;

        const transform = stroke.transform || { x: 0, y: 0, scale: 1 };

        // Check if any point in the stroke is within the eraser radius
        for (const p of stroke.points) {
            const px = p.x + transform.x;
            const py = p.y + transform.y;
            const dx = px - eraserPoint.x;
            const dy = py - eraserPoint.y;
            const distance = Math.sqrt(dx * dx + dy * dy);

            // Account for stroke width
            const strokeRadius = (stroke.strokeWidth / 2) * (transform.scale || 1);
            if (distance <= eraserRadius + strokeRadius) {
                return true;
            }
        }

        // Also check line segments between points
        for (let i = 0; i < stroke.points.length - 1; i++) {
            const p1 = stroke.points[i];
            const p2 = stroke.points[i + 1];
            const x1 = p1.x + transform.x;
            const y1 = p1.y + transform.y;
            const x2 = p2.x + transform.x;
            const y2 = p2.y + transform.y;

            const dist = this._pointToSegmentDistance(eraserPoint.x, eraserPoint.y, x1, y1, x2, y2);
            const strokeRadius = (stroke.strokeWidth / 2) * (transform.scale || 1);
            if (dist <= eraserRadius + strokeRadius) {
                return true;
            }
        }

        return false;
    }

    _pointToSegmentDistance(px, py, x1, y1, x2, y2) {
        const dx = x2 - x1;
        const dy = y2 - y1;
        const lengthSq = dx * dx + dy * dy;

        if (lengthSq === 0) {
            // Segment is a point
            return Math.sqrt((px - x1) ** 2 + (py - y1) ** 2);
        }

        // Project point onto line segment
        let t = ((px - x1) * dx + (py - y1) * dy) / lengthSq;
        t = Math.max(0, Math.min(1, t));

        const closestX = x1 + t * dx;
        const closestY = y1 + t * dy;

        return Math.sqrt((px - closestX) ** 2 + (py - closestY) ** 2);
    }

    _drawEraserCursor(point) {
        const ctx = this.activeCtx;
        const screenX = point.x * this.zoom + this.pan.x;
        const screenY = point.y * this.zoom + this.pan.y;

        ctx.save();
        ctx.strokeStyle = '#666666';
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.arc(screenX, screenY, this.eraserWidth, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.restore();
    }

    // =========================================================================
    // Rendering
    // =========================================================================

    _renderStroke(stroke, ctx, options = {}) {
        if (!stroke.points || stroke.points.length === 0) return;

        const transform = stroke.transform || { x: 0, y: 0, scale: 1 };

        // Transform points with default pressure
        const transformedPoints = stroke.points.map(p => [
            (p.x + transform.x) * this.zoom + this.pan.x,
            (p.y + transform.y) * this.zoom + this.pan.y,
            p.pressure || 0.5
        ]);

        // Single-point strokes (tap/click) should render as a dot.
        // perfect-freehand doesn't always produce an outline for 1 point, so we draw a circle fallback.
        if (transformedPoints.length === 1) {
            const [x, y] = transformedPoints[0];
            const radius = Math.max(0.5, (stroke.strokeWidth * this.zoom * (transform.scale || 1)) / 2);

            ctx.fillStyle = stroke.color;
            ctx.beginPath();
            ctx.arc(x, y, radius, 0, Math.PI * 2);
            ctx.fill();

            // Selection indicator support for dots
            if (options.selected) {
                ctx.strokeStyle = '#0066ff';
                ctx.lineWidth = 2;
                ctx.setLineDash([5, 5]);
                ctx.strokeRect(x - radius - 5, y - radius - 5, radius * 2 + 10, radius * 2 + 10);
                ctx.setLineDash([]);
            }
            return;
        }

        let rendered = false;

        // Try to use getStroke from perfect-freehand
        if (typeof getStroke === 'function') {
            try {
                // Use different options for live remote strokes to minimize snap on completion
                const freehandOpts = stroke.isRemoteLive 
                    ? {
                        ...this.freehandOptions,
                        size: stroke.strokeWidth * this.zoom * (transform.scale || 1),
                        thinning: 0.3,  // Reduced thinning for live remote strokes
                        smoothing: 0.5,  // Less smoothing during live drawing
                        streamline: 0.5,
                        simulatePressure: true,
                        last: false  // Don't treat as finished stroke
                    }
                    : {
                        ...this.freehandOptions,
                        size: stroke.strokeWidth * this.zoom * (transform.scale || 1)
                    };
                
                const outlinePoints = getStroke(transformedPoints, freehandOpts);

                if (outlinePoints && outlinePoints.length >= 2) {
                    // Use reduced opacity for live remote strokes
                    if (stroke.isRemoteLive) {
                        ctx.globalAlpha = 0.6;
                    }
                    
                    ctx.fillStyle = stroke.color;
                    ctx.beginPath();
                    
                    // Use smooth curves for the outline path
                    const [firstX, firstY] = outlinePoints[0];
                    ctx.moveTo(firstX, firstY);
                    
                    // Use quadratic curves for smoother rendering
                    for (let i = 1; i < outlinePoints.length - 1; i++) {
                        const [x0, y0] = outlinePoints[i];
                        const [x1, y1] = outlinePoints[i + 1];
                        const midX = (x0 + x1) / 2;
                        const midY = (y0 + y1) / 2;
                        ctx.quadraticCurveTo(x0, y0, midX, midY);
                    }
                    
                    // Connect to the last point
                    if (outlinePoints.length > 1) {
                        const [lastX, lastY] = outlinePoints[outlinePoints.length - 1];
                        ctx.lineTo(lastX, lastY);
                    }

                    ctx.closePath();
                    ctx.fill();
                    
                    // Reset opacity
                    if (stroke.isRemoteLive) {
                        ctx.globalAlpha = 1.0;
                    }
                    
                    rendered = true;
                }
            } catch (e) {
                console.warn('getStroke error:', e);
            }
        }

        // Fallback: smooth line rendering if getStroke failed or returned empty
        if (!rendered) {
            ctx.strokeStyle = stroke.color;
            ctx.lineWidth = stroke.strokeWidth * this.zoom * (transform.scale || 1);
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            ctx.beginPath();
            ctx.moveTo(transformedPoints[0][0], transformedPoints[0][1]);

            for (let i = 1; i < transformedPoints.length; i++) {
                ctx.lineTo(transformedPoints[i][0], transformedPoints[i][1]);
            }
            ctx.stroke();
        }

        // Draw selection box if selected
        if (options.selected) {
            const bounds = this._getStrokeBounds(stroke);
            ctx.strokeStyle = '#0066ff';
            ctx.lineWidth = 2;
            ctx.setLineDash([5, 5]);
            ctx.strokeRect(
                bounds.x * this.zoom + this.pan.x - 5,
                bounds.y * this.zoom + this.pan.y - 5,
                bounds.width * this.zoom + 10,
                bounds.height * this.zoom + 10
            );
            ctx.setLineDash([]);
        }
    }

    _renderStrokeBase(stroke) {
        this._renderStroke(stroke, this.baseCtx);
    }

    _renderStrokeActive(stroke) {
        this.activeCtx.clearRect(0, 0, this.activeCanvas.width, this.activeCanvas.height);
        this._renderStroke(stroke, this.activeCtx);

        // Redraw remote strokes
        this.remoteStrokes.forEach(remoteStroke => {
            this._renderStroke(remoteStroke, this.activeCtx);
        });

        // Redraw selection boxes
        this.selectedStrokes.forEach(strokeId => {
            const s = this.strokes.get(strokeId);
            if (s) {
                this._renderStroke(s, this.activeCtx, { selected: true });
            }
        });
    }

    _redrawBase() {
        this.baseCtx.clearRect(0, 0, this.baseCanvas.width, this.baseCanvas.height);

        // Draw background
        this.baseCtx.fillStyle = this.backgroundColor || '#ffffff';
        this.baseCtx.fillRect(0, 0, this.baseCanvas.width, this.baseCanvas.height);

        // Draw grid (optional visual aid)
        if (this.showGrid) {
            this._drawGrid();
        }

        // Collect all elements (strokes and images) and sort by zIndex
        const elements = [];
        
        this.strokes.forEach(stroke => {
            elements.push({ type: 'stroke', data: stroke, zIndex: stroke.zIndex ?? 0 });
        });
        
        this.images.forEach(image => {
            elements.push({ type: 'image', data: image, zIndex: image.zIndex ?? 0 });
        });
        
        // Sort by zIndex (lower zIndex = drawn first = appears behind)
        elements.sort((a, b) => a.zIndex - b.zIndex);
        
        // Render in z-order
        elements.forEach(element => {
            if (element.type === 'stroke') {
                this._renderStroke(element.data, this.baseCtx);
            } else if (element.type === 'image') {
                this._renderImage(element.data, this.baseCtx);
            }
        });
    }

    _renderImage(image, ctx, options = {}) {
        const transform = image.transform || { x: 0, y: 0, scale: 1 };
        const scale = transform.scale || 1;
        
        // Calculate screen position
        const screenX = (image.x + transform.x) * this.zoom + this.pan.x;
        const screenY = (image.y + transform.y) * this.zoom + this.pan.y;
        const screenWidth = image.width * scale * this.zoom;
        const screenHeight = image.height * scale * this.zoom;
        
        // Get or load image
        let imgElement = this.imageCache.get(image.id);
        
        if (!imgElement) {
            // Load image asynchronously
            imgElement = new window.Image();
            imgElement.onload = () => {
                this.imageCache.set(image.id, imgElement);
                this._redrawBase();
            };
            imgElement.src = image.data;
            return; // Don't draw until loaded
        }
        
        // Draw the image
        ctx.drawImage(imgElement, screenX, screenY, screenWidth, screenHeight);
        
        // Draw selection box and resize handles if selected
        if (options.selected) {
            // Selection border
            ctx.strokeStyle = '#0066ff';
            ctx.lineWidth = 2;
            ctx.setLineDash([5, 5]);
            ctx.strokeRect(screenX - 2, screenY - 2, screenWidth + 4, screenHeight + 4);
            ctx.setLineDash([]);
            
            // Draw resize handles
            const handleSize = 10;
            const handles = [
                { x: screenX - handleSize/2, y: screenY - handleSize/2 },                    // NW
                { x: screenX + screenWidth - handleSize/2, y: screenY - handleSize/2 },      // NE
                { x: screenX - handleSize/2, y: screenY + screenHeight - handleSize/2 },     // SW
                { x: screenX + screenWidth - handleSize/2, y: screenY + screenHeight - handleSize/2 }  // SE
            ];
            
            ctx.fillStyle = '#ffffff';
            ctx.strokeStyle = '#0066ff';
            ctx.lineWidth = 2;
            
            handles.forEach(handle => {
                ctx.fillRect(handle.x, handle.y, handleSize, handleSize);
                ctx.strokeRect(handle.x, handle.y, handleSize, handleSize);
            });
        }
    }

    _redrawActive() {
        this.activeCtx.clearRect(0, 0, this.activeCanvas.width, this.activeCanvas.height);

        // Draw remote strokes in progress
        this.remoteStrokes.forEach(remoteStroke => {
            this._renderStroke(remoteStroke, this.activeCtx);
        });

        // Draw stroke selection indicators
        this.selectedStrokes.forEach(strokeId => {
            const stroke = this.strokes.get(strokeId);
            if (stroke) {
                const bounds = this._getStrokeBounds(stroke);
                this.activeCtx.strokeStyle = '#0066ff';
                this.activeCtx.lineWidth = 2;
                this.activeCtx.setLineDash([5, 5]);
                this.activeCtx.strokeRect(
                    bounds.x * this.zoom + this.pan.x - 5,
                    bounds.y * this.zoom + this.pan.y - 5,
                    bounds.width * this.zoom + 10,
                    bounds.height * this.zoom + 10
                );
                this.activeCtx.setLineDash([]);
            }
        });

        // Draw image selection indicators
        this.selectedImages.forEach(imageId => {
            const image = this.images.get(imageId);
            if (image) {
                this._renderImage(image, this.activeCtx, { selected: true });
            }
        });

        // Draw remote user cursors
        this._renderRemoteCursors();
    }

    _renderRemoteCursors() {
        const ctx = this.activeCtx;
        const now = Date.now();
        
        this.remoteUsers.forEach((user, oduserId) => {
            // Skip stale cursors (not updated in 10 seconds)
            if (now - user.lastSeen > 10000) return;
            
            if (!user.cursor) return;
            
            // Transform canvas coordinates to screen coordinates
            const screenX = user.cursor.x * this.zoom + this.pan.x;
            const screenY = user.cursor.y * this.zoom + this.pan.y;
            
            // Skip if cursor is off screen
            if (screenX < -50 || screenX > this.activeCanvas.width + 50 ||
                screenY < -50 || screenY > this.activeCanvas.height + 50) {
                return;
            }
            
            // Draw cursor pointer
            ctx.save();
            ctx.translate(screenX, screenY);
            
            // Cursor shape (arrow-like pointer)
            ctx.fillStyle = user.color;
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 2;
            
            ctx.beginPath();
            ctx.moveTo(0, 0);
            ctx.lineTo(0, 18);
            ctx.lineTo(5, 14);
            ctx.lineTo(9, 22);
            ctx.lineTo(12, 21);
            ctx.lineTo(8, 13);
            ctx.lineTo(14, 13);
            ctx.closePath();
            
            ctx.stroke();
            ctx.fill();
            
            // Draw name label
            const name = user.name || 'Anonymous';
            ctx.font = '12px -apple-system, BlinkMacSystemFont, sans-serif';
            const textWidth = ctx.measureText(name).width;
            
            // Label background
            ctx.fillStyle = user.color;
            ctx.beginPath();
            ctx.roundRect(16, 16, textWidth + 10, 20, 4);
            ctx.fill();
            
            // Label text
            ctx.fillStyle = '#ffffff';
            ctx.fillText(name, 21, 30);
            
            ctx.restore();
        });
    }

    _drawGrid() {
        const gridSize = 20 * this.zoom;
        const offsetX = this.pan.x % gridSize;
        const offsetY = this.pan.y % gridSize;

        // Determine grid color based on background brightness
        const isDarkBg = this._isDarkColor(this.backgroundColor);
        this.baseCtx.strokeStyle = isDarkBg ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.06)';
        this.baseCtx.lineWidth = 1;

        // Vertical lines
        for (let x = offsetX; x < this.baseCanvas.width; x += gridSize) {
            this.baseCtx.beginPath();
            this.baseCtx.moveTo(x, 0);
            this.baseCtx.lineTo(x, this.baseCanvas.height);
            this.baseCtx.stroke();
        }

        // Horizontal lines
        for (let y = offsetY; y < this.baseCanvas.height; y += gridSize) {
            this.baseCtx.beginPath();
            this.baseCtx.moveTo(0, y);
            this.baseCtx.lineTo(this.baseCanvas.width, y);
            this.baseCtx.stroke();
        }
    }

    _isDarkColor(hexColor) {
        // Convert hex to RGB and calculate brightness
        const hex = hexColor.replace('#', '');
        const r = parseInt(hex.substr(0, 2), 16);
        const g = parseInt(hex.substr(2, 2), 16);
        const b = parseInt(hex.substr(4, 2), 16);
        const brightness = (r * 299 + g * 587 + b * 114) / 1000;
        return brightness < 128;
    }

    // =========================================================================
    // Hit Testing & Selection
    // =========================================================================

    _hitTestImage(x, y) {
        // Check images in reverse order (top to bottom)
        const imageIds = Array.from(this.images.keys()).reverse();

        for (const imageId of imageIds) {
            const image = this.images.get(imageId);
            const bounds = this._getImageBounds(image);

            // Simple bounding box test
            if (x >= bounds.x && x <= bounds.x + bounds.width &&
                y >= bounds.y && y <= bounds.y + bounds.height) {
                return imageId;
            }
        }

        return null;
    }

    _getImageBounds(image) {
        const transform = image.transform || { x: 0, y: 0, scale: 1 };
        return {
            x: image.x + transform.x,
            y: image.y + transform.y,
            width: image.width * (transform.scale || 1),
            height: image.height * (transform.scale || 1)
        };
    }

    _hitTestResizeHandle(x, y) {
        const handleSize = 12 / this.zoom;  // Handle size in canvas coordinates
        
        // Only check selected images
        for (const imageId of this.selectedImages) {
            const image = this.images.get(imageId);
            if (!image) continue;
            
            const bounds = this._getImageBounds(image);
            const handles = this._getResizeHandles(bounds, handleSize);
            
            for (const [handle, rect] of Object.entries(handles)) {
                if (x >= rect.x && x <= rect.x + rect.size &&
                    y >= rect.y && y <= rect.y + rect.size) {
                    return { imageId, handle };
                }
            }
        }
        
        return null;
    }

    _getResizeHandles(bounds, handleSize) {
        const halfHandle = handleSize / 2;
        return {
            nw: { x: bounds.x - halfHandle, y: bounds.y - halfHandle, size: handleSize },
            ne: { x: bounds.x + bounds.width - halfHandle, y: bounds.y - halfHandle, size: handleSize },
            sw: { x: bounds.x - halfHandle, y: bounds.y + bounds.height - halfHandle, size: handleSize },
            se: { x: bounds.x + bounds.width - halfHandle, y: bounds.y + bounds.height - halfHandle, size: handleSize }
        };
    }

    _getResizeCursor(handle) {
        const cursors = {
            nw: 'nwse-resize',
            se: 'nwse-resize',
            ne: 'nesw-resize',
            sw: 'nesw-resize'
        };
        return cursors[handle] || 'default';
    }

    _hitTest(x, y) {
        // Check strokes in reverse order (top to bottom)
        const strokeIds = Array.from(this.strokes.keys()).reverse();

        for (const strokeId of strokeIds) {
            const stroke = this.strokes.get(strokeId);
            const bounds = this._getStrokeBounds(stroke);

            // Simple bounding box test
            if (x >= bounds.x && x <= bounds.x + bounds.width &&
                y >= bounds.y && y <= bounds.y + bounds.height) {
                return strokeId;
            }
        }

        return null;
    }

    _getStrokeBounds(stroke) {
        if (!stroke.points || stroke.points.length === 0) {
            return { x: 0, y: 0, width: 0, height: 0 };
        }

        const transform = stroke.transform || { x: 0, y: 0, scale: 1 };
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

        stroke.points.forEach(p => {
            const px = p.x + transform.x;
            const py = p.y + transform.y;
            minX = Math.min(minX, px);
            minY = Math.min(minY, py);
            maxX = Math.max(maxX, px);
            maxY = Math.max(maxY, py);
        });

        const padding = stroke.strokeWidth / 2;
        return {
            x: minX - padding,
            y: minY - padding,
            width: maxX - minX + stroke.strokeWidth,
            height: maxY - minY + stroke.strokeWidth
        };
    }

    // =========================================================================
    // Selection & Manipulation
    // =========================================================================

    selectStroke(strokeId) {
        this.selectedStrokes.clear();
        this.selectedStrokes.add(strokeId);
        this._redrawActive();
    }

    selectMultiple(strokeIds) {
        strokeIds.forEach(id => this.selectedStrokes.add(id));
        this._redrawActive();
    }

    selectAll() {
        this.strokes.forEach((_, id) => this.selectedStrokes.add(id));
        this.images.forEach((_, id) => this.selectedImages.add(id));
        this._redrawActive();
    }

    deselectAll() {
        this.selectedStrokes.clear();
        this.selectedImages.clear();
        this._redrawActive();
    }

    deleteSelected() {
        const deletedStrokeIds = Array.from(this.selectedStrokes);
        const deletedImageIds = Array.from(this.selectedImages);

        // Save strokes for history before deleting
        const deletedStrokes = deletedStrokeIds.map(id => {
            const stroke = this.strokes.get(id);
            return stroke ? { ...stroke } : null;
        }).filter(s => s !== null);

        // Save images for history before deleting
        const deletedImages = deletedImageIds.map(id => {
            const image = this.images.get(id);
            return image ? { ...image } : null;
        }).filter(i => i !== null);

        // Add to history
        if (deletedStrokes.length > 0) {
            this._addToHistory({
                type: 'stroke-delete',
                strokes: deletedStrokes
            });
        }
        if (deletedImages.length > 0) {
            this._addToHistory({
                type: 'image-delete',
                images: deletedImages
            });
        }

        deletedStrokeIds.forEach(id => {
            this.strokes.delete(id);
        });

        deletedImageIds.forEach(id => {
            this.images.delete(id);
            this.imageCache.delete(id);
        });

        this.selectedStrokes.clear();
        this.selectedImages.clear();
        this._redrawBase();
        this._redrawActive();

        // Emit delete events
        if (this.onStrokeDelete && deletedStrokeIds.length > 0) {
            this.onStrokeDelete({ strokeIds: deletedStrokeIds });
        }
        if (this.onImageDelete && deletedImageIds.length > 0) {
            this.onImageDelete({ imageIds: deletedImageIds });
        }
    }

    // =========================================================================
    // Zoom & Pan
    // =========================================================================

    setZoom(level) {
        this.zoom = Math.min(this.maxZoom, Math.max(this.minZoom, level));
        this._redrawBase();
        this._redrawActive();
    }

    zoomIn() {
        this.setZoom(this.zoom * 1.2);
    }

    zoomOut() {
        this.setZoom(this.zoom / 1.2);
    }

    resetZoom() {
        this.zoom = 1;
        this.pan = { x: 0, y: 0 };
        this._redrawBase();
        this._redrawActive();
    }

    // =========================================================================
    // Mode & Settings
    // =========================================================================

    setMode(mode) {
        this._previousMode = this.mode;
        this.mode = mode;
        if (mode !== 'select') {
            this.deselectAll();
        }
        this._updateCursor();
    }

    setColor(color) {
        this.color = color;
    }

    setStrokeWidth(width) {
        this.strokeWidth = width;
    }

    setEraserWidth(width) {
        this.eraserWidth = width;
    }

    setBackgroundColor(color) {
        this.backgroundColor = color;
        this._redrawBase();
    }

    setShowGrid(show) {
        this.showGrid = show;
        this._redrawBase();
    }

    _updateCursor() {
        switch (this.mode) {
            case 'draw':
                this.activeCanvas.style.cursor = 'crosshair';
                break;
            case 'select':
                this.activeCanvas.style.cursor = 'default';
                break;
            case 'pan':
                this.activeCanvas.style.cursor = this.isPanning ? 'grabbing' : 'grab';
                break;
            case 'erase':
                this.activeCanvas.style.cursor = 'none';  // We'll draw a custom cursor
                break;
        }
    }

    // =========================================================================
    // Remote Events
    // =========================================================================

    applyRemoteStrokePoint(data) {
        const { strokeId, point, color, strokeWidth } = data;

        if (!this.remoteStrokes.has(strokeId)) {
            this.remoteStrokes.set(strokeId, {
                id: strokeId,
                points: [],
                color: color || '#888888',
                strokeWidth: strokeWidth || 4,
                transform: { x: 0, y: 0, scale: 1 },
                isRemoteLive: true  // Flag for live remote strokes
            });
        }

        const remoteStroke = this.remoteStrokes.get(strokeId);
        remoteStroke.points.push(point);

        // Render on active canvas
        this._redrawActive();
        this._renderStroke(remoteStroke, this.activeCtx);
    }

    applyRemoteStrokeComplete(data) {
        const { strokeId, points, color, strokeWidth, transform, zIndex } = data;

        // Remove from remote strokes
        this.remoteStrokes.delete(strokeId);

        // Add to permanent strokes
        const stroke = {
            id: strokeId,
            points: points,
            color: color || '#000000',
            strokeWidth: strokeWidth || 4,
            transform: transform || { x: 0, y: 0, scale: 1 },
            zIndex: zIndex ?? this.nextZIndex++
        };
        
        // Update nextZIndex if received zIndex is higher
        if (zIndex !== undefined && zIndex >= this.nextZIndex) {
            this.nextZIndex = zIndex + 1;
        }
        
        this.strokes.set(strokeId, stroke);

        // Redraw
        this._redrawBase();
        this._redrawActive();
    }

    applyRemoteStrokeUpdate(data) {
        const { strokeId, transform } = data;
        const stroke = this.strokes.get(strokeId);

        if (stroke) {
            stroke.transform = transform;
            this._redrawBase();
            this._redrawActive();
        }
    }

    applyRemoteStrokeDelete(data) {
        const strokeIds = data.strokeIds || [data.strokeId];

        strokeIds.forEach(id => {
            this.strokes.delete(id);
            this.selectedStrokes.delete(id);
        });

        this._redrawBase();
        this._redrawActive();
    }

    applyRemoteClear() {
        this.strokes.clear();
        this.selectedStrokes.clear();
        this.images.clear();
        this.selectedImages.clear();
        this.imageCache.clear();
        this.nextZIndex = 0;  // Reset z-index counter
        this._redrawBase();
        this._redrawActive();
    }

    // Image remote events
    applyRemoteImageAdd(data) {
        const { imageId, data: imageData, x, y, width, height, transform, zIndex } = data;
        
        const image = {
            id: imageId,
            data: imageData,
            x: x || 0,
            y: y || 0,
            width: width || 200,
            height: height || 200,
            transform: transform || { x: 0, y: 0, scale: 1 },
            zIndex: zIndex ?? this.nextZIndex++
        };
        
        // Update nextZIndex if received zIndex is higher
        if (zIndex !== undefined && zIndex >= this.nextZIndex) {
            this.nextZIndex = zIndex + 1;
        }
        
        this.images.set(imageId, image);
        
        // Load and cache the image
        const img = new window.Image();
        img.onload = () => {
            this.imageCache.set(imageId, img);
            this._redrawBase();
        };
        img.src = imageData;
    }

    applyRemoteImageUpdate(data) {
        const { imageId, transform, x, y, width, height } = data;
        const image = this.images.get(imageId);

        if (image) {
            if (transform) image.transform = transform;
            if (x !== undefined) image.x = x;
            if (y !== undefined) image.y = y;
            if (width !== undefined) image.width = width;
            if (height !== undefined) image.height = height;
            this._redrawBase();
            this._redrawActive();
        }
    }

    applyRemoteImageDelete(data) {
        const imageIds = data.imageIds || [data.imageId];

        imageIds.forEach(id => {
            this.images.delete(id);
            this.selectedImages.delete(id);
            this.imageCache.delete(id);
        });

        this._redrawBase();
        this._redrawActive();
    }

    // =========================================================================
    // History Management (Undo/Redo)
    // =========================================================================

    _addToHistory(action) {
        // Remove any redo history when a new action is performed
        if (this.historyIndex < this.history.length - 1) {
            this.history = this.history.slice(0, this.historyIndex + 1);
        }

        // Add the action to history
        this.history.push(action);
        this.historyIndex++;

        // Limit history size
        if (this.history.length > this.maxHistorySize) {
            this.history.shift();
            this.historyIndex--;
        }
    }

    undo() {
        if (this.historyIndex < 0) return;

        const action = this.history[this.historyIndex];
        this._undoAction(action);
        this.historyIndex--;
    }

    redo() {
        if (this.historyIndex >= this.history.length - 1) return;

        this.historyIndex++;
        const action = this.history[this.historyIndex];
        this._redoAction(action);
    }

    _undoAction(action) {
        switch (action.type) {
            case 'stroke-add':
                // Remove the stroke
                this.strokes.delete(action.strokeId);
                this.selectedStrokes.delete(action.strokeId);
                if (this.onStrokeDelete) {
                    this.onStrokeDelete({ strokeIds: [action.strokeId] });
                }
                break;

            case 'stroke-delete':
                // Restore the strokes
                action.strokes.forEach(stroke => {
                    this.strokes.set(stroke.id, { ...stroke });
                });
                // Note: We don't emit restore events - the strokes are already gone from server
                // This is local-only undo. For full collaborative undo, server support is needed.
                break;

            case 'stroke-move':
                // Restore original transforms
                action.changes.forEach(change => {
                    const stroke = this.strokes.get(change.strokeId);
                    if (stroke) {
                        stroke.transform = { ...change.oldTransform };
                        if (this.onStrokeUpdate) {
                            this.onStrokeUpdate({
                                strokeId: change.strokeId,
                                transform: { ...change.oldTransform }
                            });
                        }
                    }
                });
                break;

            case 'image-add':
                // Remove the image
                this.images.delete(action.imageId);
                this.selectedImages.delete(action.imageId);
                this.imageCache.delete(action.imageId);
                if (this.onImageDelete) {
                    this.onImageDelete({ imageIds: [action.imageId] });
                }
                break;

            case 'image-delete':
                // Restore the images
                action.images.forEach(image => {
                    this.images.set(image.id, { ...image });
                    // Reload image into cache
                    const img = new window.Image();
                    img.onload = () => {
                        this.imageCache.set(image.id, img);
                        this._redrawBase();
                    };
                    img.src = image.data;
                });
                break;

            case 'image-move':
            case 'image-resize':
                // Restore original state
                action.changes.forEach(change => {
                    const image = this.images.get(change.imageId);
                    if (image) {
                        image.x = change.oldState.x;
                        image.y = change.oldState.y;
                        image.width = change.oldState.width;
                        image.height = change.oldState.height;
                        image.transform = { ...change.oldState.transform };
                        if (this.onImageUpdate) {
                            this.onImageUpdate({
                                imageId: change.imageId,
                                x: image.x,
                                y: image.y,
                                width: image.width,
                                height: image.height,
                                transform: { ...image.transform }
                            });
                        }
                    }
                });
                break;
        }

        this._redrawBase();
        this._redrawActive();
    }

    _redoAction(action) {
        switch (action.type) {
            case 'stroke-add':
                // Re-add the stroke
                this.strokes.set(action.strokeId, { ...action.stroke });
                // Emit to sync
                if (this.onStrokeComplete) {
                    this.onStrokeComplete({
                        strokeId: action.strokeId,
                        points: action.stroke.points,
                        color: action.stroke.color,
                        strokeWidth: action.stroke.strokeWidth,
                        transform: action.stroke.transform
                    });
                }
                break;

            case 'stroke-delete':
                // Re-delete the strokes
                action.strokes.forEach(stroke => {
                    this.strokes.delete(stroke.id);
                    this.selectedStrokes.delete(stroke.id);
                });
                if (this.onStrokeDelete) {
                    this.onStrokeDelete({ strokeIds: action.strokes.map(s => s.id) });
                }
                break;

            case 'stroke-move':
                // Apply new transforms
                action.changes.forEach(change => {
                    const stroke = this.strokes.get(change.strokeId);
                    if (stroke) {
                        stroke.transform = { ...change.newTransform };
                        if (this.onStrokeUpdate) {
                            this.onStrokeUpdate({
                                strokeId: change.strokeId,
                                transform: { ...change.newTransform }
                            });
                        }
                    }
                });
                break;

            case 'image-add':
                // Re-add the image
                this.images.set(action.imageId, { ...action.image });
                // Reload into cache
                const img = new window.Image();
                img.onload = () => {
                    this.imageCache.set(action.imageId, img);
                    this._redrawBase();
                };
                img.src = action.image.data;
                // Emit to sync
                if (this.onImageAdd) {
                    this.onImageAdd(action.image);
                }
                break;

            case 'image-delete':
                // Re-delete the images
                action.images.forEach(image => {
                    this.images.delete(image.id);
                    this.selectedImages.delete(image.id);
                    this.imageCache.delete(image.id);
                });
                if (this.onImageDelete) {
                    this.onImageDelete({ imageIds: action.images.map(i => i.id) });
                }
                break;

            case 'image-move':
            case 'image-resize':
                // Apply new state
                action.changes.forEach(change => {
                    const image = this.images.get(change.imageId);
                    if (image) {
                        image.x = change.newState.x;
                        image.y = change.newState.y;
                        image.width = change.newState.width;
                        image.height = change.newState.height;
                        image.transform = { ...change.newState.transform };
                        if (this.onImageUpdate) {
                            this.onImageUpdate({
                                imageId: change.imageId,
                                x: image.x,
                                y: image.y,
                                width: image.width,
                                height: image.height,
                                transform: { ...image.transform }
                            });
                        }
                    }
                });
                break;
        }

        this._redrawBase();
        this._redrawActive();
    }

    canUndo() {
        return this.historyIndex >= 0;
    }

    canRedo() {
        return this.historyIndex < this.history.length - 1;
    }

    clearHistory() {
        this.history = [];
        this.historyIndex = -1;
    }

    // =========================================================================
    // Utilities
    // =========================================================================

    clear() {
        this.strokes.clear();
        this.selectedStrokes.clear();
        this.images.clear();
        this.selectedImages.clear();
        this.imageCache.clear();
        this.nextZIndex = 0;  // Reset z-index counter
        this._redrawBase();
        this._redrawActive();

        if (this.onClear) {
            this.onClear();
        }
    }

    resize() {
        // Don't resize while actively drawing - it clears the canvas
        if (this.isDrawing) {
            this._pendingResize = true;
            return;
        }

        const container = this.baseCanvas.parentElement;
        const width = container.clientWidth || window.innerWidth;
        const height = container.clientHeight || window.innerHeight;

        // Check if size actually changed
        if (this.baseCanvas.width === width && this.baseCanvas.height === height) {
            return;
        }

        // Update canvas sizes (this clears them)
        this.baseCanvas.width = width;
        this.baseCanvas.height = height;
        this.activeCanvas.width = width;
        this.activeCanvas.height = height;

        // Redraw
        this._redrawBase();
        this._redrawActive();
    }

    exportStrokes() {
        return Array.from(this.strokes.values());
    }

    exportImages() {
        return Array.from(this.images.values());
    }

    importStrokes(strokesArray) {
        this.strokes.clear();
        let maxZIndex = -1;
        
        strokesArray.forEach(stroke => {
            // Ensure stroke has a zIndex
            if (stroke.zIndex === undefined) {
                stroke.zIndex = this.nextZIndex++;
            }
            maxZIndex = Math.max(maxZIndex, stroke.zIndex);
            this.strokes.set(stroke.id, stroke);
        });
        
        // Update nextZIndex to be higher than any imported stroke
        if (maxZIndex >= this.nextZIndex) {
            this.nextZIndex = maxZIndex + 1;
        }
        
        this._redrawBase();
        this._redrawActive();
    }

    importImages(imagesArray) {
        this.images.clear();
        this.imageCache.clear();
        let maxZIndex = this.nextZIndex - 1;
        
        imagesArray.forEach(image => {
            // Ensure image has a zIndex
            if (image.zIndex === undefined) {
                image.zIndex = this.nextZIndex++;
            }
            maxZIndex = Math.max(maxZIndex, image.zIndex);
            this.images.set(image.id, image);
            
            // Load and cache the image
            const img = new window.Image();
            img.onload = () => {
                this.imageCache.set(image.id, img);
                this._redrawBase();
            };
            img.src = image.data;
        });
        
        // Update nextZIndex to be higher than any imported image
        if (maxZIndex >= this.nextZIndex) {
            this.nextZIndex = maxZIndex + 1;
        }
    }

    // =========================================================================
    // Remote User / Cursor Management
    // =========================================================================

    setLocalUser(userId, name) {
        this.localUserId = userId;
        this.localUserName = name;
        // Assign a consistent color based on userId
        const colorIndex = Math.abs(this._hashCode(userId)) % this.cursorColors.length;
        this.localUserColor = this.cursorColors[colorIndex];
    }

    updateRemoteUser(userId, data) {
        if (userId === this.localUserId) return;  // Ignore self
        
        let user = this.remoteUsers.get(userId);
        if (!user) {
            const colorIndex = Math.abs(this._hashCode(userId)) % this.cursorColors.length;
            user = {
                name: data.name || 'Anonymous',
                color: this.cursorColors[colorIndex],
                cursor: null,
                lastSeen: Date.now()
            };
            this.remoteUsers.set(userId, user);
        }
        
        if (data.name) user.name = data.name;
        if (data.cursor) user.cursor = data.cursor;
        user.lastSeen = Date.now();
        
        this._redrawActive();
    }

    removeRemoteUser(userId) {
        this.remoteUsers.delete(userId);
        this._redrawActive();
    }

    getRemoteUsers() {
        const users = [];
        const now = Date.now();
        this.remoteUsers.forEach((user, oduserId) => {
            if (now - user.lastSeen < 10000) {
                users.push({
                    oduserId,
                    name: user.name,
                    color: user.color,
                    cursor: user.cursor
                });
            }
        });
        return users;
    }

    jumpToUser(userId) {
        const user = this.remoteUsers.get(userId);
        if (!user || !user.cursor) return false;
        
        // Center the view on the user's cursor position
        const centerX = this.activeCanvas.width / 2;
        const centerY = this.activeCanvas.height / 2;
        
        this.pan.x = centerX - user.cursor.x * this.zoom;
        this.pan.y = centerY - user.cursor.y * this.zoom;
        
        this._redrawBase();
        this._redrawActive();
        return true;
    }

    _hashCode(str) {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash;
        }
        return hash;
    }

    _generateId(prefix = 'stroke') {
        return prefix + '-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Whiteboard;
}
