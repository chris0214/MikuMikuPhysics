"""Quick smoke test: try registering MikuMikuPhysics inside Blender."""
import sys
import traceback

ADDON_PARENT = r"F:\help2"


def main():
    if ADDON_PARENT not in sys.path:
        sys.path.append(ADDON_PARENT)
    import MikuMikuPhysics

    try:
        MikuMikuPhysics.register()
        print("REGISTER_OK")
        MikuMikuPhysics.unregister()
        print("UNREGISTER_OK")
    except Exception:
        traceback.print_exc()
        print("REGISTER_FAILED")
        sys.exit(1)


main()
