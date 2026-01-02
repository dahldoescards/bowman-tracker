#!/bin/bash
# Production Build Script
# Minifies CSS and JavaScript for production deployment

set -e

FRONTEND_DIR="frontend"
BUILD_DIR="frontend/dist"

echo "🔨 Building production assets..."

# Create dist directory
mkdir -p $BUILD_DIR/css
mkdir -p $BUILD_DIR/js

# Check if uglifyjs and cleancss are available
if ! command -v uglifyjs &> /dev/null; then
    echo "📦 Installing uglify-js..."
    npm install -g uglify-js
fi

if ! command -v cleancss &> /dev/null; then
    echo "📦 Installing clean-css-cli..."
    npm install -g clean-css-cli
fi

# Minify JavaScript
echo "📦 Minifying JavaScript..."
uglifyjs $FRONTEND_DIR/js/app.js \
    --compress \
    --mangle \
    --output $BUILD_DIR/js/app.min.js

# Minify CSS files
echo "📦 Minifying CSS..."
cleancss -o $BUILD_DIR/css/styles.min.css $FRONTEND_DIR/css/styles.css
cleancss -o $BUILD_DIR/css/components.min.css $FRONTEND_DIR/css/components.css
cleancss -o $BUILD_DIR/css/utilities.min.css $FRONTEND_DIR/css/utilities.css

# Create combined CSS
cat $BUILD_DIR/css/styles.min.css \
    $BUILD_DIR/css/components.min.css \
    $BUILD_DIR/css/utilities.min.css > $BUILD_DIR/css/bundle.min.css

# Copy index.html and update paths for production
echo "📦 Creating production index.html..."
sed -e 's|css/styles.css|dist/css/bundle.min.css|g' \
    -e 's|css/components.css||g' \
    -e 's|css/utilities.css||g' \
    -e 's|js/app.js?v=[0-9]*|dist/js/app.min.js|g' \
    $FRONTEND_DIR/index.html > $BUILD_DIR/index.html

# Remove empty link tags
sed -i '' '/<link rel="stylesheet" href="">$/d' $BUILD_DIR/index.html 2>/dev/null || \
sed -i '/<link rel="stylesheet" href="">$/d' $BUILD_DIR/index.html

# Calculate sizes
ORIGINAL_JS=$(wc -c < $FRONTEND_DIR/js/app.js)
MINIFIED_JS=$(wc -c < $BUILD_DIR/js/app.min.js)
JS_REDUCTION=$(echo "scale=1; (1 - $MINIFIED_JS / $ORIGINAL_JS) * 100" | bc)

ORIGINAL_CSS=$(cat $FRONTEND_DIR/css/*.css | wc -c)
MINIFIED_CSS=$(wc -c < $BUILD_DIR/css/bundle.min.css)
CSS_REDUCTION=$(echo "scale=1; (1 - $MINIFIED_CSS / $ORIGINAL_CSS) * 100" | bc)

echo ""
echo "✅ Build complete!"
echo ""
echo "📊 Size reductions:"
echo "   JavaScript: $ORIGINAL_JS → $MINIFIED_JS bytes (-${JS_REDUCTION}%)"
echo "   CSS: $ORIGINAL_CSS → $MINIFIED_CSS bytes (-${CSS_REDUCTION}%)"
echo ""
echo "📁 Production files in: $BUILD_DIR/"
