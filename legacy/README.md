# Legacy Scripts

This directory contains archived versions of the original ground station application.

## Files

- **GS_cansat.py**: Original monolithic ground station with all functionality in a single file
- **GS_noplots.py**: Variant without real-time plotting features
- **GS_vslv.py**: Variant optimized for VSLV team operations
- **test.py**: Legacy test/development scripts

## Status

These scripts are **no longer actively maintained**. The codebase has been refactored into a modular architecture located in the `application/` directory.

## Migration Notes

If you need to reference functionality from these scripts:

1. **For current development**: Use the modular version in `application/`
2. **For reference**: These files document the original implementation approach
3. **For compatibility**: The new modular system implements all core functionality with improved structure

## Why These Are Archived

The original monolithic scripts had:
- All code in a single large file
- Mixed UI and business logic
- Difficult to maintain and extend
- No clear separation of concerns

The new modular structure provides:
- Clean separation into `core/` and `ui/` modules
- Configuration-driven behavior
- Better testability
- Easier maintenance and feature additions
