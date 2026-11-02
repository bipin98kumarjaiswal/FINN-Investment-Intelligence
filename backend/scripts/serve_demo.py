"""Render Free start command: python -m scripts.serve_demo"""
import os
import sys

from scripts.demo_snapshot import SnapshotError, restore_snapshot


def main():
    try:
        restored = restore_snapshot()
    except SnapshotError as exc:
        print(f'[FINN] Startup refused: {exc}', file=sys.stderr, flush=True)
        return 1
    # Existing FastAPI initialization may perform harmless writes to this
    # ephemeral copy; it never updates the immutable private GitHub snapshot.
    os.environ['FINN_DB_PATH'] = restored['runtime_path']
    import uvicorn
    uvicorn.run('app.main:app', host='0.0.0.0', port=int(os.environ.get('PORT','8000')),
                workers=1, reload=False, access_log=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
