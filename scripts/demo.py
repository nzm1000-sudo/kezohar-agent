"""Start only a loopback demo; no deployment or model/configuration changes."""
from pathlib import Path
import sys
import argparse
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
parser = argparse.ArgumentParser(description='הדגמת Kezohar המקומית')
parser.add_argument('--port', type=int, default=8711)
args = parser.parse_args()
if not 8700 <= args.port <= 8799:
    parser.error('port must be between 8700 and 8799')
import uvicorn
uvicorn.run('kezohar.demo:app', host='127.0.0.1', port=args.port, access_log=False)
