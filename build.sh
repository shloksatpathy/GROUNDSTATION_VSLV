#!/bin/bash
# Build script for VSSSIC Ground Station V3

set -e

echo "========================================"
echo "Building VSSSIC Ground Station V3"
echo "========================================"

# Check if PyInstaller is installed
if ! python3 -m pip show pyinstaller > /dev/null 2>&1; then
    echo "Installing PyInstaller..."
    python3 -m pip install pyinstaller
fi

# Create dist directory
mkdir -p dist

# Build the executable
echo "Building standalone executable..."
pyinstaller build.spec

echo ""
echo "========================================"
echo "Build Complete!"
echo "========================================"
echo "Executable location: ./dist/VSSSIC_Ground_Station"
echo ""
echo "To run the application:"
echo "  ./dist/VSSSIC_Ground_Station"
echo ""
echo "On first launch it creates config/ and data/ alongside the executable."
echo "Edit dist/config/config.json to change team ID, baud rate, or map origin."
echo ""
